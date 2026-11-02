"""Synthetic body loss is a missing image, never a recovered frame or usage."""
import copy,json,sqlite3,tempfile,threading,time,unittest
from email.message import Message
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from capture import Camera as Transport,Collector,Store
from camera_status import ReadinessTransportError
from test_capture_continuation import Camera,configure,READY,request
from test_capture import JPEG,headers
import capture_recovery as r

EVIDENCE=dict(stage='jpeg_body',expected_bytes=100,received_bytes=20,frame_id='synthetic-2',
    captured_at='2026-01-01T00:00:00+00:00',expected_sha256='a'*64,clock_id='synthetic-boot',monotonic_us=1000000)

class TransferRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
        self.camera=Camera([True,r.BodyTimeout(EVIDENCE),True,True])
        self.worker=configure(Collector(self.store,self.camera,6))
    def tearDown(self):self.temp.cleanup()
    def rows(self,table):
        with self.store.connect() as db:return db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
    def failed(self):self.worker.once();self.worker.once()
    def test_timeout_is_durable_unknown_with_no_partial_image(self):
        self.failed()
        self.assertEqual([row[1] for row in self.rows('continuous_capture_outcomes')],['committed','unknown'])
        self.assertEqual(self.rows('continuous_capture_outcomes')[-1][3],'camera_timeout')
        self.assertEqual(len(self.rows('capture_events')),1)
        self.assertEqual(len(list((self.store.root/'images').iterdir())),1)
        self.assertEqual(json.loads(self.rows('capture_transfer_timeouts')[0][1]),EVIDENCE)
        self.assertEqual(self.worker.recovery_status()['state'],'waiting_for_transfer_recovery')
        self.assertTrue(self.store.publication_blocked(1));self.assertFalse(self.worker.stop.is_set())
    def test_probe_acceptance_and_new_request_are_separate_cycles(self):
        self.failed();old={t:self.rows(t) for t in ('frames','capture_events','failures','capture_failure_boundaries','continuous_capture_outcomes','capture_transfer_timeouts')}
        old_id=self.worker.transfer_attempt;self.worker.once()
        self.assertEqual(self.camera.calls,2)
        self.assertEqual(len(self.rows('capture_continuations')),1)
        self.assertEqual(self.rows('capture_continuations')[0][4],r.TRANSFER_POLICY)
        self.assertTrue(self.store.publication_blocked(1))
        self.worker.once();self.assertEqual(self.camera.calls,3)
        self.assertNotEqual(self.rows('continuous_capture_attempts')[-1][0],old_id)
        for table,rows in old.items():self.assertEqual(self.rows(table)[:len(rows)],rows)
        with self.store.connect() as db:self.assertTrue(r.boundary(db,2))
    def test_busy_device_only_gets_passive_probes(self):
        self.failed();self.camera.ready['state']='busy'
        for _ in range(8):self.worker.once()
        self.assertEqual(self.camera.calls,2);self.assertEqual(self.rows('capture_continuations'),[])
        self.assertEqual(self.worker.readiness_retry_delay,60)
        self.assertFalse(self.worker.stop.is_set())
    def test_readiness_outage_preserves_failures_and_later_recovers(self):
        self.failed()
        with patch.object(self.camera,'readiness',side_effect=ReadinessTransportError()):
            for _ in range(7):self.worker.once()
        self.assertEqual(self.camera.calls,2);self.assertEqual(len(self.rows('failures')),8)
        self.assertEqual(self.worker.readiness_retry_delay,60)
        self.worker.once();self.worker.once();self.assertEqual(self.camera.calls,3)
        self.assertEqual(len(self.rows('failures')),8)
    def test_nontransient_probe_failure_holds(self):
        self.failed()
        with patch.object(self.camera,'readiness',side_effect=ValueError('camera_authentication_failed')):self.worker.once()
        self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.rows('capture_continuations'),[])
    def test_nonready_device_holds(self):
        self.failed();self.camera.ready['state']='settings_unavailable';self.worker.once()
        self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.camera.calls,2)
    def test_historical_string_timeout_is_not_automatically_accepted(self):
        self.camera.results=iter([ValueError('camera_timeout'),True]);self.worker.once();self.worker.once()
        self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.camera.calls,1)
        self.assertEqual(self.rows('capture_transfer_timeouts'),[])
    def test_restart_before_acceptance_keeps_unknown_hold(self):
        self.failed()
        restarted=configure(Collector(Store(self.temp.name),self.camera,6,recovery_floor=2));restarted.once()
        self.assertTrue(restarted.stop.is_set());self.assertEqual(self.camera.calls,2)
    def test_restart_after_acceptance_keeps_original_unknown(self):
        self.failed();self.worker.once()
        restarted=configure(Collector(Store(self.temp.name),self.camera,6,recovery_floor=2));restarted.once()
        self.assertFalse(restarted.stop.is_set());self.assertEqual(self.camera.calls,3)
        self.assertEqual(self.rows('continuous_capture_outcomes')[1][1],'unknown')
    def test_context_change_before_probe_holds_without_probe(self):
        self.failed();count=self.camera.probes;self.worker.continuation_context=lambda:{'changed':True};self.worker.once()
        self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.camera.probes,count)
    def test_context_change_during_probe_holds(self):
        self.failed();original=self.camera.readiness
        def changed():self.worker.continuation_context=lambda:{'changed':True};return original()
        with patch.object(self.camera,'readiness',side_effect=changed):self.worker.once()
        self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.rows('capture_continuations'),[])
    def test_new_failure_during_probe_invalidates_review(self):
        self.failed();original=self.camera.readiness
        def changed():self.store.fail('camera_connection_failed');return original()
        with patch.object(self.camera,'readiness',side_effect=changed):self.worker.once()
        self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.rows('capture_continuations'),[])
    def test_pending_attempt_blocks_recovery(self):
        self.failed()
        with self.store.connect() as db:db.execute('INSERT INTO continuous_capture_attempts VALUES(?,?,?,?)',('b'*32,1,1,'2026-01-01T00:00:00+00:00'))
        self.worker.once();self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.rows('capture_continuations'),[])
    def test_storage_reserve_blocks_recovery(self):
        self.failed()
        with patch.object(self.store,'require_space',side_effect=ValueError('storage_low_space')):self.worker.once()
        self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.camera.calls,2)
    def test_failure_commit_error_cannot_release_hold(self):
        self.worker.once()
        with patch.object(self.store,'fail',side_effect=sqlite3.OperationalError('synthetic')):self.worker.once()
        self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.rows('capture_continuations'),[])
        self.assertIsNone(self.worker.transfer_attempt)
    def test_acceptance_commit_error_holds(self):
        self.failed()
        with patch.object(r,'accept_continuation',side_effect=sqlite3.OperationalError('synthetic')):self.worker.once()
        self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.rows('capture_continuations'),[])
    def test_shutdown_never_admits_probe_or_post(self):
        self.failed();count=self.camera.probes;self.worker.request_stop();self.worker.once()
        self.assertEqual(self.camera.calls,2);self.assertEqual(self.camera.probes,count)
    def test_shutdown_during_probe_prevents_acceptance(self):
        self.failed();original=self.camera.readiness
        def shutdown():self.worker.request_stop();return original()
        with patch.object(self.camera,'readiness',side_effect=shutdown):self.worker.once()
        self.assertEqual(self.rows('capture_continuations'),[]);self.assertEqual(self.camera.calls,2)
    def test_repeated_timeouts_back_off_without_replaying(self):
        self.camera.results=iter([r.BodyTimeout(EVIDENCE) for _ in range(6)]+[True])
        ids=[];delays=[]
        for _ in range(6):
            self.worker.once();ids.append(self.worker.transfer_attempt);delays.append(self.worker.readiness_retry_delay)
            self.worker.once()
        self.assertEqual(delays,[6,12,24,48,60,60]);self.assertEqual(len(set(ids)),6)
        self.assertEqual(self.camera.calls,6);self.worker.once();self.assertEqual(self.worker.transfer_failures,0)
    def test_recovery_wait_starts_after_timeout_and_honors_slow_cadence(self):
        self.worker.interval=90
        with patch('capture.time.monotonic',return_value=100):self.failed()
        self.assertEqual(self.worker.transfer_not_before,190)
    def test_recovery_does_not_reset_rejection_streak(self):
        self.camera.results=iter([r.FreshnessRejected(),r.FreshnessRejected(),r.BodyTimeout(EVIDENCE),r.FreshnessRejected(),True])
        for _ in range(5):self.worker.once()
        self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.camera.calls,4)
        self.assertEqual(self.worker.recovery_status()['consecutive_rejections'],3)
    def test_transfer_records_are_immutable(self):
        self.failed()
        for sql in ('DELETE FROM capture_transfer_timeouts','UPDATE capture_transfer_timeouts SET evidence_json=\'{}\''):
            with self.assertRaises(sqlite3.IntegrityError),self.store.connect() as db:db.execute(sql)
    def test_manual_endpoint_cannot_claim_policy(self):
        self.camera.results=iter([ValueError('camera_timeout')]);self.worker.once();action=request(self.worker)
        action['approval_reference']=r.TRANSFER_POLICY
        with self.assertRaisesRegex(ValueError,'reserved_policy'):self.worker.continue_after_gap(action)
    def test_corrupted_binding_cannot_be_accepted(self):
        self.failed()
        with self.store.connect() as db:db.execute("UPDATE continuous_capture_outcomes SET finished_at='2026-01-01T00:00:00+00:00' WHERE outcome='unknown'")
        self.worker.once();self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.rows('capture_continuations'),[])
    def test_no_runtime_context_means_no_automatic_policy(self):
        self.worker.continuation_context=None;self.failed()
        self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.rows('capture_transfer_timeouts'),[])

class BodyTimeoutTransportTests(unittest.TestCase):
    def response(self):
        class Response:
            status=200
            def __init__(self):
                self.headers=headers();self.headers['Content-Type']='image/jpeg';self.headers['Content-Length']=str(len(JPEG))
                self.headers['X-AIEdge-Clock-Id']='synthetic';self.headers['X-AIEdge-Capture-Monotonic-Us']='100'
                self.closed=False;self.calls=0
            def __enter__(self):return self
            def __exit__(self,*args):self.closed=True
            def read1(self,count):
                self.calls+=1
                if self.calls==1:return JPEG[:3]
                raise TimeoutError('private socket details')
        return Response()
    def test_body_timeout_retains_only_safe_metadata_and_closes_response(self):
        camera=Transport('http://127.0.0.1');response=self.response()
        with patch.object(camera.opener,'open',return_value=response) as opened:
            with self.assertRaises(r.BodyTimeout) as caught:camera.capture()
        self.assertEqual(opened.call_count,1);self.assertTrue(response.closed)
        self.assertEqual(caught.exception.evidence['received_bytes'],3)
        self.assertNotIn('private',json.dumps(caught.exception.evidence));self.assertEqual(str(caught.exception),'camera_timeout')
    def test_timeout_before_headers_is_not_qualified(self):
        camera=Transport('http://127.0.0.1')
        with patch.object(camera.opener,'open',side_effect=TimeoutError()):
            with self.assertRaises(ValueError) as caught:camera.capture()
        self.assertNotIsInstance(caught.exception,r.BodyTimeout)
    def test_missing_or_duplicate_metadata_cannot_qualify(self):
        camera=Transport('http://127.0.0.1')
        for name in ('X-AIEdge-Clock-Id','X-AIEdge-SHA256','X-AIEdge-Frame-Id','X-AIEdge-Captured-At'):
            for duplicate in (False,True):
                response=self.response()
                if duplicate:response.headers[name]=response.headers[name]
                else:del response.headers[name]
                with patch.object(camera.opener,'open',return_value=response),self.assertRaises(ValueError) as caught:camera.capture()
                self.assertNotIsInstance(caught.exception,r.BodyTimeout)
    def test_invalid_byte_counts_are_rejected(self):
        for key,value in [('received_bytes',-1),('received_bytes',100),('expected_bytes',True),('monotonic_us',False)]:
            with self.assertRaises(ValueError):r.BodyTimeout(dict(EVIDENCE,**{key:value}))
    def test_real_socket_partial_body_timeout_closes_without_second_post(self):
        posts=[];release=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                posts.append(self.path);self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200)
                for key,value in headers().items():self.send_header(key,value)
                self.send_header('Content-Type','image/jpeg');self.send_header('Content-Length',str(len(JPEG)))
                self.send_header('X-AIEdge-Clock-Id','synthetic');self.send_header('X-AIEdge-Capture-Monotonic-Us','1')
                self.end_headers();self.wfile.write(JPEG[:3]);self.wfile.flush();release.wait(2)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            camera=Transport('http://127.0.0.1:'+str(server.server_port))
            with self.assertRaises(r.BodyTimeout) as caught:camera.capture(deadline=time.monotonic()+.3)
            self.assertEqual(caught.exception.evidence['received_bytes'],3);self.assertEqual(posts,['/api/v1/capture'])
        finally:release.set();server.shutdown();server.server_close();thread.join(2)

if __name__=='__main__':unittest.main()
