import threading,time,unittest,urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from lifecycle import ServiceRuntime

class LifecycleTests(unittest.TestCase):
    def make_server(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):self.send_response(200);self.end_headers();self.wfile.write(b'ok')
            def log_message(self,*args):pass
        return ThreadingHTTPServer(('127.0.0.1',0),Handler)

    def test_stop_waits_for_inflight_worker_cleanup(self):
        class Worker:
            def __init__(self):self.stop=threading.Event();self.started=threading.Event();self.cleanup=threading.Event();self.release=threading.Event()
            def run(self):
                self.started.set();self.stop.wait();self.release.wait();self.cleanup.set()
        workers=[Worker(),Worker()];server=self.make_server();runtime=ServiceRuntime(server,workers,timeout=2)
        result=[];thread=threading.Thread(target=lambda:result.append(runtime.run()));thread.start()
        try:
            self.assertTrue(runtime.ready.wait(2))
            for worker in workers:self.assertTrue(worker.started.wait(2))
            with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/',timeout=2) as response:self.assertEqual(response.read(),b'ok')
            runtime.request_stop();runtime.request_stop()
            for worker in workers:self.assertTrue(worker.stop.is_set())
            self.assertTrue(thread.is_alive())
            for worker in workers:worker.release.set()
            thread.join(3);self.assertFalse(thread.is_alive())
            self.assertEqual(result,[True])
            for worker in workers:self.assertTrue(worker.cleanup.is_set())
        finally:
            for worker in workers:worker.release.set()
            runtime.request_stop();thread.join(3)

    def test_unresponsive_worker_has_bounded_shutdown(self):
        class Worker:
            def __init__(self):self.stop=threading.Event();self.release=threading.Event()
            def run(self):self.release.wait()
        worker=Worker();server=self.make_server();runtime=ServiceRuntime(server,[worker],timeout=.1)
        result=[];thread=threading.Thread(target=lambda:result.append(runtime.run()));thread.start()
        try:
            self.assertTrue(runtime.ready.wait(2));start=time.monotonic();runtime.request_stop()
            thread.join(2);self.assertFalse(thread.is_alive());self.assertLess(time.monotonic()-start,1.5)
            self.assertEqual(result,[False])
        finally:
            worker.release.set();runtime.request_stop();thread.join(2)
            for task in runtime.threads:task.join(2)

if __name__=='__main__':unittest.main()
