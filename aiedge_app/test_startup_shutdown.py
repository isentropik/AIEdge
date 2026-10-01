"""Stop lifecycle checks. Windows signal dispatch is not a Linux container test."""
import contextlib, hashlib, io, json, signal, socket, tempfile, threading, time, unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch
from http_server import AppHTTPServer
from lifecycle import ServiceRuntime, StartupSignals, StartupStopped


class StartupTests(unittest.TestCase):
    def test_stop_intent_survives_attachment_and_restores_signal_handlers(self):
        previous = {name:signal.getsignal(name) for name in (signal.SIGINT, signal.SIGTERM)}
        with StartupSignals() as scope:
            self.assertEqual(signal.getsignal(signal.SIGTERM), scope.request_stop)
            signal.raise_signal(signal.SIGTERM)
            signal.raise_signal(signal.SIGINT)
            with self.assertRaises(StartupStopped): scope.checkpoint()
            runtime = SimpleNamespace(request_stop=unittest.mock.Mock())
            scope.attach(runtime)
            runtime.request_stop.assert_called_once()
        for name, handler in previous.items():self.assertEqual(signal.getsignal(name), handler)

    def test_stopping_during_options_never_opens_store_or_starts_capture(self):
        import service
        def options(*_):
            signal.raise_signal(signal.SIGTERM)
            return {'interval_seconds':30, 'capture_enabled':True}, {'state':'ready'}
        with patch('sys.argv',['service.py']), patch.object(service,'load_options',side_effect=options), \
             patch.object(service,'Store') as store, patch.object(service,'Collector') as collector, \
             patch.object(service,'AppHTTPServer') as server, contextlib.redirect_stdout(io.StringIO()) as output:
            service.main()
        store.assert_not_called();collector.assert_not_called();server.assert_not_called()
        event=json.loads(output.getvalue())
        self.assertEqual(event, {'event':'aiedge_stopped', 'phase':'startup', 'workers':0})

    def test_stopping_during_model_load_never_opens_http_or_starts_workers(self):
        import service
        previous=signal.getsignal(signal.SIGTERM)
        def model(*_):
            signal.raise_signal(signal.SIGTERM)
            return object()
        with patch('sys.argv',['service.py','--native-library','fixture','--models','fixture','--calibration-profile','fixture']), \
             patch.object(service,'load_options',return_value=({'interval_seconds':30,'capture_enabled':True},{'state':'ready'})), \
             patch.object(service,'Store'), patch.object(service,'create_reader',side_effect=model), \
             patch.dict('sys.modules',{'reader':SimpleNamespace(Reader=object), 'recognition':SimpleNamespace(Recognition=unittest.mock.Mock())}), \
             patch.object(service,'Collector') as collector, patch.object(service,'AppHTTPServer') as server, \
             contextlib.redirect_stdout(io.StringIO()) as output:
            service.main()
        collector.assert_not_called();server.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['phase'],'startup')
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)


class RuntimeTests(unittest.TestCase):
    def server(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):self.send_response(200);self.end_headers();self.wfile.write(b'ok')
            def log_message(self,*args):pass
        return AppHTTPServer(('127.0.0.1',0), Handler)

    def test_stop_before_run_does_not_start_workers_or_shutdown_thread(self):
        server=self.server();worker=SimpleNamespace(stop=threading.Event(),run=unittest.mock.Mock())
        runtime=ServiceRuntime(server,[worker],timeout=.2)
        runtime.request_stop()
        self.assertTrue(runtime.run());worker.run.assert_not_called()
        self.assertFalse(runtime.ready.is_set());self.assertIsNone(runtime.shutdown_thread)
        self.assertEqual(server.socket.fileno(),-1)

    def test_signal_in_ready_to_http_gap_finishes_without_deadlock(self):
        server=self.server();runtime=ServiceRuntime(server,[],timeout=.5)
        class Ready(threading.Event):
            def set(self):
                super().set();signal.raise_signal(signal.SIGTERM)
        runtime.ready=Ready();previous=signal.getsignal(signal.SIGTERM)
        self.assertTrue(runtime.run())
        self.assertIsNotNone(runtime.shutdown_thread)
        self.assertFalse(runtime.shutdown_thread.is_alive())
        self.assertEqual(signal.getsignal(signal.SIGTERM),previous)

    def test_concurrent_stop_requests_have_one_shutdown_and_no_leaked_thread(self):
        server=self.server();runtime=ServiceRuntime(server,[],timeout=1)
        result=[];thread=threading.Thread(target=lambda:result.append(runtime.run()))
        with patch.object(server,'shutdown',wraps=server.shutdown) as shutdown:
            thread.start();self.assertTrue(runtime.ready.wait(2))
            barrier=threading.Barrier(9)
            def stop():barrier.wait();runtime.request_stop()
            callers=[threading.Thread(target=stop) for _ in range(8)]
            for caller in callers:caller.start()
            barrier.wait()
            for caller in callers:caller.join(2);self.assertFalse(caller.is_alive())
            thread.join(2);self.assertFalse(thread.is_alive())
            self.assertEqual(result,[True]);self.assertEqual(shutdown.call_count,1)
            self.assertFalse(runtime.shutdown_thread.is_alive())

    def test_partial_http_request_is_drained_at_deadline_and_reported_as_timeout(self):
        server=self.server();runtime=ServiceRuntime(server,[],timeout=.05)
        result=[];output=io.StringIO()
        def run():
            with contextlib.redirect_stdout(output):result.append(runtime.run())
        thread=threading.Thread(target=run);thread.start();client=None
        try:
            self.assertTrue(runtime.ready.wait(2))
            client=socket.create_connection(server.server_address,timeout=2)
            client.sendall(b'GET / HTTP/1.1\r\nHost: ')
            deadline=time.monotonic()+2
            while not server._requests:
                if time.monotonic()>deadline:self.fail('request was not admitted')
                time.sleep(.005)
            start=time.monotonic();runtime.request_stop();thread.join(2)
            self.assertFalse(thread.is_alive());self.assertLess(time.monotonic()-start,1)
            self.assertEqual(result,[False])
            event=json.loads(output.getvalue().splitlines()[-1])
            self.assertEqual(event['event'],'aiedge_shutdown_timeout')
            self.assertFalse(event['requests_drained'])
        finally:
            if client:client.close()
            runtime.request_stop();thread.join(2)

    def test_stop_during_camera_transfer_saves_only_the_inflight_frame(self):
        from capture import Camera,Collector,Store,now
        # Transport envelope only. No real image or model accuracy is tested.
        blob=b'\xff\xd8lifecycle-fixture\xff\xd9'
        entered,release=threading.Event(),threading.Event()
        class CameraFixture(BaseHTTPRequestHandler):
            count=0;checks=0
            def log_message(self,*args):pass
            def do_GET(self):
                assert self.path=='/api/v1/camera'
                CameraFixture.checks+=1
                body=json.dumps({'protocol_version':1,'mode':'remote-camera','state':'ready',
                    'camera_available':True,'settings_ready':True,'clock_synchronized':True,
                    'capture_path':'/api/v1/capture','capture_method':'POST',
                    'capture_clock_metadata':True,'image_sha256':True}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length','0')));CameraFixture.count+=1
                self.send_response(200);self.send_header('Content-Type','image/jpeg');self.send_header('Content-Length',str(len(blob)))
                self.send_header('X-AIEdge-Frame-Id','fixture-'+str(CameraFixture.count))
                self.send_header('X-AIEdge-Captured-At',now());self.send_header('X-AIEdge-SHA256',hashlib.sha256(blob).hexdigest())
                self.end_headers();entered.set();release.wait(2);self.wfile.write(blob)
        camera_server=ThreadingHTTPServer(('127.0.0.1',0),CameraFixture)
        camera_thread=threading.Thread(target=camera_server.serve_forever);camera_thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                store=Store(directory);collector=Collector(store,Camera(f'http://127.0.0.1:{camera_server.server_port}'),30)
                runtime=ServiceRuntime(self.server(),[collector],timeout=2)
                result=[];thread=threading.Thread(target=lambda:result.append(runtime.run()));thread.start()
                try:
                    self.assertTrue(runtime.ready.wait(2));self.assertTrue(entered.wait(2))
                    runtime.request_stop();self.assertTrue(collector.stop.is_set());release.set()
                    thread.join(3);self.assertFalse(thread.is_alive());self.assertEqual(result,[True])
                    self.assertEqual(CameraFixture.count,1)
                    self.assertEqual(CameraFixture.checks,1)
                    self.assertEqual(Store(directory).status()['captures'],1,collector.last_error)
                    self.assertFalse(store.status()['training_allowed'])
                finally:release.set();runtime.request_stop();thread.join(3)
        finally:release.set();camera_server.shutdown();camera_thread.join(3);camera_server.server_close()
