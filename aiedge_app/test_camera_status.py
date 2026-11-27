"""Passive readiness and scheduled admission using a real loopback HTTP server."""
import contextlib,json,tempfile,threading,time,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from capture import Camera,Collector,Store
from camera_status import validate
from test_capture import JPEG,headers

READY={'protocol_version':1,'mode':'remote-camera','state':'ready',
       'camera_available':True,'settings_ready':True,'clock_synchronized':True,
       'capture_path':'/api/v1/capture','capture_method':'POST',
       'capture_clock_metadata':True,'image_sha256':True}

@contextlib.contextmanager
def fixture():
    class Handler(BaseHTTPRequestHandler):
        payload=READY.copy();body=None;status=200;extra=[];auth=None
        gets=0;posts=0;frame=0;header_delay=0
        def log_message(self,*args):pass
        def do_GET(self):
            type(self).gets+=1
            if self.header_delay:time.sleep(self.header_delay)
            assert self.path=='/api/v1/camera'
            type(self).auth=self.headers.get('Authorization')
            blob=self.body if self.body is not None else json.dumps(self.payload).encode()
            self.send_response(self.status)
            self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(blob)))
            for k,v in self.extra:self.send_header(k,v)
            self.end_headers();self.wfile.write(blob)
        def do_POST(self):
            type(self).posts+=1;type(self).frame+=1
            assert self.path=='/api/v1/capture'
            self.rfile.read(int(self.headers['Content-Length']))
            self.send_response(200);self.send_header('Content-Type','image/jpeg')
            self.send_header('Content-Length',str(len(JPEG)))
            for k,v in headers(str(self.frame)).items():self.send_header(k,v)
            self.end_headers();self.wfile.write(JPEG)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=lambda:server.serve_forever(poll_interval=.01));thread.start()
    try:yield Camera(f'http://127.0.0.1:{server.server_port}'),Handler
    finally:server.shutdown();thread.join();server.server_close()

class CameraStatusTests(unittest.TestCase):
    def test_passive_check_authenticates_without_capture_or_echoing_extra_fields(self):
        with fixture() as (camera,device):
            device.payload['private']='PRIVATE-CREDENTIAL'
            camera.token='fixture-token'
            self.assertEqual(camera.readiness(),READY)
            self.assertEqual(device.auth,'Bearer fixture-token')
            self.assertEqual((device.gets,device.posts),(1,0))
    def test_strict_protocol_and_ready_consistency(self):
        for key,value in [('protocol_version',True),('protocol_version',2),
                          ('capture_method','GET'),('capture_path','/other'),
                          ('image_sha256',False),('settings_ready',False),
                          ('clock_synchronized',False),('camera_available',None),
                          ('mode',[]),('state',{})]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                validate(READY|{key:value})
    def test_malformed_duplicate_or_ambiguous_response_does_not_capture(self):
        with fixture() as (camera,device):
            for body,extra in [(b'not json',[]),(b'{"state":"ready","state":"busy"}',[]),
                               (json.dumps(READY).encode(),[('Content-Length','1')]),
                               (json.dumps(READY).encode(),[('Content-Type','text/plain')]),
                               (json.dumps(READY).encode(),[('Transfer-Encoding','chunked')])]:
                device.body,device.extra=body,extra
                with self.subTest(body=body,extra=extra),self.assertRaises(ValueError):camera.readiness()
            self.assertEqual(device.posts,0)
    def test_errors_are_sanitized_without_immediate_retries(self):
        with fixture() as (camera,device):
            device.body=b'PRIVATE-CREDENTIAL'
            for status,code in [(401,'camera_authentication_failed'),(404,'camera_api_unavailable'),(500,'camera_http_error')]:
                device.status=status
                with self.subTest(status=status),self.assertRaisesRegex(ValueError,'^'+code+'$'):camera.readiness()
            self.assertEqual((device.gets,device.posts),(3,0))
    def test_nonfreshness_readiness_failure_holds_without_post(self):
        for state,code,changes in [
                ('settings_unavailable','camera_settings_unavailable',{'settings_ready':False}),
                ('startup_recovery','camera_startup_recovery',{'settings_ready':False}),
                ('clock_unsynchronized','camera_clock_unsynchronized',{'clock_synchronized':False}),
                ('camera_unavailable','camera_unavailable',{'camera_available':False}),
                ('demo_mode','camera_demo_mode',{})]:
            with self.subTest(state=state),fixture() as (camera,device),tempfile.TemporaryDirectory() as directory:
                store=Store(directory);collector=Collector(store,camera,30)
                device.payload=READY|{'state':state}|changes
                collector.once()
                self.assertEqual(collector.last_error['error'],code)
                self.assertEqual(collector.camera_state['state'],state)
                self.assertEqual((device.posts,store.status()['captures']),(0,0))
                device.payload=READY.copy();collector.once()
                self.assertTrue(collector.stop.is_set())
                self.assertEqual((device.gets,device.posts,store.status()['captures']),(1,0,0))
                self.assertEqual(store.status()['failures'],1)
                self.assertFalse(store.status()['training_allowed'])
    def test_busy_before_capture_retries_only_the_passive_probe(self):
        from capture_recovery import boundary
        with fixture() as (camera,device),tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            collector=Collector(store,camera,10)
            device.payload=READY|{'state':'busy','camera_available':None}
            for count in (1,2):
                if count==2:
                    collector=Collector(Store(directory),camera,10)
                collector.once()
                status=collector.recovery_status()
                self.assertEqual(status['state'],'waiting_for_camera')
                self.assertEqual(status['failure_count'],1)
                self.assertEqual(status['last_busy_period']['busy_probes'],count)
                self.assertEqual(collector.last_error['error'],'camera_busy')
                self.assertEqual((device.gets,device.posts),(count,0))
            device.payload=READY.copy()
            collector.once()
            self.assertEqual((device.gets,device.posts),(3,1))
            self.assertEqual(collector.recovery_status()['state'],'ready')
            with store.connect() as db:
                self.assertTrue(boundary(db,1))
                self.assertEqual(db.execute('SELECT count(*) FROM continuous_capture_attempts').fetchone()[0],1)
            device.payload=READY|{'state':'busy'}
            collector.once()
            status=collector.recovery_status()
            self.assertEqual(status['failure_count'],2)
            self.assertEqual(status['last_busy_period']['busy_probes'],1)
            self.assertEqual(status['last_busy_period']['after_event_id'],1)

    def test_busy_period_keeps_configured_cadence_and_first_ready_slot(self):
        from test_delivery_timing import Clock
        for interval in (10,30):
            with self.subTest(interval=interval), fixture() as (camera,device), tempfile.TemporaryDirectory() as directory:
                worker=Collector(Store(directory),camera,interval)
                clock=Clock()
                delays=[]
                device.payload=READY|{'state':'busy','camera_available':None}
                def wait(delay):
                    delays.append(delay)
                    clock.advance(delay)
                    if device.gets==8:
                        device.payload=READY.copy()
                    elif device.gets==9:
                        worker.request_stop()
                with patch('capture.time.monotonic',clock), patch.object(worker.stop,'wait',side_effect=wait):
                    worker.run()
                self.assertEqual(delays,[interval]*9)
                self.assertEqual((device.gets,device.posts),(9,1))
                status=worker.recovery_status()
                self.assertEqual(status['failure_count'],1)
                self.assertEqual(status['last_busy_period']['busy_probes'],8)

    def test_unmarked_legacy_failure_and_busy_after_post_remain_separate(self):
        from test_capture_continuation import Camera as TestCamera,configure
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            store.fail('camera_busy')  # Historical failure without passive probe evidence.
            camera=TestCamera([ValueError('camera_busy')])
            worker=configure(Collector(store,camera,10))
            camera.ready['state']='busy'
            worker.once()
            self.assertEqual(worker.recovery_status()['failure_count'],2)
            store.fail('camera_connection_failed')
            worker.once()
            self.assertEqual(worker.recovery_status()['failure_count'],4)
            camera.ready['state']='ready'
            worker.once()
            status=worker.recovery_status()
            self.assertEqual((status['state'],status['failure_count']),('held',5))
            self.assertEqual(status['last_busy_period']['busy_probes'],1)
            self.assertEqual(status['recent_attempts'][-1]['outcome'],'unknown')
            self.assertEqual(camera.calls,1)

    def test_brief_reboot_after_busy_is_distinct_from_extended_network_outage(self):
        from datetime import datetime,timedelta,timezone
        from camera_status import ReadinessTransportError
        from test_capture_continuation import Camera as TestCamera
        start=datetime(2026,11,26,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            camera=TestCamera([True])
            worker=Collector(Store(directory),camera,10)
            camera.ready['state']='busy'
            with patch('capture.now',return_value=start.isoformat()):
                worker.once()
            worker=Collector(Store(directory),camera,10)
            for seconds in (10,40,60,61,75):
                stamp=(start+timedelta(seconds=seconds)).isoformat()
                with patch('capture.now',return_value=stamp), patch.object(camera,'readiness',side_effect=ReadinessTransportError()):
                    worker.once()
                status=worker.recovery_status()
                if seconds<=60:
                    self.assertEqual(status['failure_count'],1)
                    self.assertEqual(worker.readiness_retry_delay,0)
                else:
                    self.assertGreater(status['failure_count'],1)
                    self.assertGreater(worker.readiness_retry_delay,0)
            self.assertEqual((status['last_busy_period']['busy_probes'],status['last_busy_period']['unreachable_probes']),(1,3))
            self.assertEqual(status['failure_count'],3)
            camera.ready['state']='ready'
            worker.once()
            self.assertEqual(camera.calls,1)
            self.assertEqual(worker.recovery_status()['state'],'ready')
    def test_connection_failure_is_visible_and_does_not_capture(self):
        with fixture() as (camera,device),tempfile.TemporaryDirectory() as directory:
            collector=Collector(Store(directory),camera,30)
            with patch.object(camera,'readiness',side_effect=ValueError('camera_connection_failed')):
                collector.once()
            self.assertEqual(collector.camera_state['state'],'unavailable')
            self.assertEqual(collector.last_error['error'],'camera_connection_failed')
            self.assertEqual((device.gets,device.posts),(0,0))

    def test_slow_valid_readiness_response_uses_one_passive_get(self):
        with fixture() as (camera,device):
            device.header_delay=5.3
            self.assertEqual(camera.readiness()['state'],'ready')
            self.assertEqual((device.gets,device.posts),(1,0))

    def test_scheduled_header_timeouts_share_one_budget_and_restore_slow_probe(self):
        from camera_status import ReadinessTransportError
        from test_delivery_timing import Clock
        camera=Camera('http://127.0.0.1:1')
        clock=Clock()
        stop=threading.Event()
        budgets=[]
        # Healthy initially, then two stranded connections, then a full outage.
        # The next two healthy but slow replies must get their full allowance.
        delays=iter((.1,None,None,.2,None,None,None,8.5,8.5))
        def response(camera,header_deadline,absolute):
            delay=next(delays)
            budgets.append((round(header_deadline-clock(),1),round(absolute-clock(),1)))
            if delay is None:
                clock.advance(header_deadline-clock())
                raise ReadinessTransportError('connect_or_headers',TimeoutError())
            self.assertGreater(header_deadline-clock(),delay)
            clock.advance(delay)
            return READY
        with patch('camera_status._get_status',side_effect=response),patch('camera_status.time.monotonic',clock):
            self.assertEqual(camera.scheduled_readiness(stop),READY)
            self.assertEqual(camera.scheduled_readiness(stop),READY)
            with self.assertRaises(ReadinessTransportError):
                camera.scheduled_readiness(stop)
            self.assertEqual(camera.scheduled_readiness(stop),READY)
            self.assertEqual(camera.scheduled_readiness(stop),READY)
        self.assertEqual(budgets,[(10,10),(2,10),(2,8),(6,6),(2,10),(2,8),(6,6),(10,10),(10,10)])

    def test_only_scheduled_pre_header_timeout_allows_a_second_get(self):
        from camera_status import ReadinessTransportError
        camera=Camera('http://127.0.0.1:1')
        stop=threading.Event()
        for error in (ReadinessTransportError('status_body',TimeoutError()),
                      ReadinessTransportError('connect_or_headers',ConnectionRefusedError()),
                      ValueError('camera_authentication_failed'),ValueError('camera_status_invalid')):
            camera.fast_readiness=True
            with self.subTest(error=repr(error)),patch('camera_status._get_status',side_effect=error) as get:
                with self.assertRaises(type(error)):
                    camera.scheduled_readiness(stop)
                self.assertEqual(get.call_count,1)
        def interrupted(*args):
            stop.set()
            raise ReadinessTransportError('connect_or_headers',TimeoutError())
        with patch('camera_status._get_status',side_effect=interrupted) as get:
            camera.fast_readiness=True
            with self.assertRaises(ReadinessTransportError):
                camera.scheduled_readiness(stop)
            self.assertEqual(get.call_count,1)

    def test_busy_reply_restores_one_full_probe_during_maintenance(self):
        from camera_status import ReadinessTransportError
        from test_delivery_timing import Clock
        camera=Camera('http://127.0.0.1:1')
        stop=threading.Event()
        clock=Clock()
        budgets=[]
        def status(camera,header,absolute):
            budgets.append(header-clock())
            if len(budgets)==1:return READY
            if len(budgets)==2:return dict(READY,state='busy')
            raise ReadinessTransportError('connect_or_headers',TimeoutError())
        with patch('camera_status._get_status',side_effect=status),patch('camera_status.time.monotonic',clock):
            camera.scheduled_readiness(stop)
            self.assertEqual(camera.scheduled_readiness(stop)['state'],'busy')
            for _ in range(2):
                with self.assertRaises(ReadinessTransportError):camera.scheduled_readiness(stop)
        self.assertEqual(budgets,[10,2,10,10])

if __name__=='__main__':unittest.main()
