"""Synthetic transport and ledger tests; never contact a physical camera."""
import copy,json,sqlite3,tempfile,threading,time,unittest,urllib.error
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from capture import Camera as Transport,Collector,Store
from camera_status import ReadinessTransportError
from test_capture_continuation import Camera,configure,request
import test_transfer_recovery
import capture_recovery as r

class RequestRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
        self.camera=Camera([True,r.RequestTimeout(),True,True])
        self.worker=configure(Collector(self.store,self.camera,6))
    def tearDown(self):self.temp.cleanup()
    def rows(self,table):
        with self.store.connect() as db:return db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
    def failed(self):self.worker.once();self.worker.once()
    def test_timeout_preserves_unknown_and_separate_provenance(self):
        self.failed()
        self.assertEqual(self.rows('continuous_capture_outcomes')[-1][1:4],('unknown',None,'camera_timeout'))
        self.assertEqual(len(self.rows('capture_request_timeouts')),1)
        self.assertEqual(self.rows('capture_transfer_timeouts'),[])
        self.assertFalse(self.worker.stop.is_set());self.assertTrue(self.store.publication_blocked(1))
        self.assertEqual(self.worker.recovery_status()['transfer_failure_evidence'],{'stage':'awaiting_response'})
    def test_probe_accept_new_request_separate_cycles_preserve_rows(self):
        self.failed()
        tables=('frames','capture_events','capture_clocks','failures','capture_failure_boundaries','continuous_capture_attempts','continuous_capture_outcomes','capture_request_timeouts')
        old={t:self.rows(t) for t in tables}
        self.worker.once();self.assertEqual(self.camera.calls,2)
        self.assertEqual(self.rows('capture_continuations')[0][4],r.REQUEST_POLICY)
        self.assertTrue(self.store.publication_blocked(1))
        self.worker.once();self.assertEqual(self.camera.calls,3)
        self.assertFalse(self.store.publication_blocked(2))
        with self.store.connect() as db:self.assertTrue(r.boundary(db,2))
        for t,rows in old.items():self.assertEqual(self.rows(t)[:len(rows)],rows)
    def test_restart_pending_recovers_only_after_ready(self):
        self.failed();worker=configure(Collector(Store(self.temp.name),self.camera,6,recovery_floor=2))
        self.assertFalse(worker.stop.is_set());self.assertEqual(self.camera.calls,2)
        self.assertGreater(worker.transfer_not_before,time.monotonic())
        worker.once();self.assertEqual(self.camera.calls,2)
        worker.once();self.assertEqual(self.camera.calls,3)
        self.assertEqual(self.rows('continuous_capture_outcomes')[1][1],'unknown')
    def test_restart_accepted_does_not_accept_twice(self):
        self.failed();self.worker.once()
        worker=configure(Collector(Store(self.temp.name),self.camera,6));worker.once()
        self.assertEqual(len(self.rows('capture_continuations')),1);self.assertEqual(self.camera.calls,3)
    def test_busy_and_readiness_outage_only_probe_backoff(self):
        self.failed();self.camera.ready['state']='busy'
        for _ in range(8):self.worker.once()
        self.assertEqual(self.worker.readiness_retry_delay,60)
        self.assertEqual(self.camera.calls,2);self.assertEqual(self.rows('capture_continuations'),[])
        with patch.object(self.camera,'readiness',side_effect=ReadinessTransportError()):self.worker.once()
        self.assertFalse(self.worker.stop.is_set());self.assertEqual(self.camera.calls,2)
        self.camera.ready['state']='ready';self.worker.once();self.worker.once()
        self.assertEqual(self.camera.calls,3)
    def test_repeated_timeouts_back_off_without_inventing_events(self):
        self.camera.results=iter([r.RequestTimeout() for _ in range(9)])
        for _ in range(8):
            self.worker.once();self.worker.once()
        self.assertEqual(self.camera.calls,8);self.assertEqual(self.rows('capture_events'),[])
        self.assertEqual(len(self.rows('capture_continuations')),8)
        self.assertEqual(self.worker.readiness_retry_delay,60)
        self.assertTrue(all(x[1]=='unknown' for x in self.rows('continuous_capture_outcomes')))
    def test_restart_context_change_holds_before_probe(self):
        self.failed();worker=configure(Collector(Store(self.temp.name),self.camera,6))
        worker.continuation_context=lambda:{'changed':True};probes=self.camera.probes
        worker.once();self.assertTrue(worker.stop.is_set());self.assertEqual(self.camera.probes,probes)
    def test_context_change_during_probe_holds(self):
        self.failed();original=self.camera.readiness
        def changed():self.worker.continuation_context=lambda:{'changed':True};return original()
        with patch.object(self.camera,'readiness',side_effect=changed):self.worker.once()
        self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.rows('capture_continuations'),[])
    def test_ledger_change_during_probe_holds(self):
        self.failed();original=self.camera.readiness
        def changed():self.store.fail('synthetic_failure');return original()
        with patch.object(self.camera,'readiness',side_effect=changed):self.worker.once()
        self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.rows('capture_continuations'),[])
    def test_auth_failure_stays_held(self):
        self.failed()
        with patch.object(self.camera,'readiness',side_effect=ValueError('camera_authentication_failed')):self.worker.once()
        self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.rows('capture_continuations'),[])
    def test_shutdown_never_restarts_capture(self):
        self.failed();self.worker.request_stop();self.worker.once()
        self.assertEqual(self.camera.calls,2);self.assertEqual(self.rows('capture_continuations'),[])
    def test_restart_after_auth_fault_keeps_hard_hold(self):
        self.test_auth_failure_stays_held()
        worker=configure(Collector(Store(self.temp.name),self.camera,6));probes=self.camera.probes
        worker.once();self.assertTrue(worker.stop.is_set());self.assertEqual(self.camera.probes,probes)
    def test_restart_after_readiness_outage_can_recover(self):
        self.failed()
        with patch.object(self.camera,'readiness',side_effect=ReadinessTransportError()):self.worker.once()
        worker=configure(Collector(Store(self.temp.name),self.camera,6));worker.once();worker.once()
        self.assertFalse(worker.stop.is_set());self.assertEqual(self.camera.calls,3)
    def test_two_unresolved_attempts_keep_hold(self):
        self.failed()
        with self.store.connect() as db:
            db.execute('INSERT INTO continuous_capture_attempts VALUES(?,?,?,?)',('second',1,1,'2026-01-01T00:00:00+00:00'))
        worker=configure(Collector(Store(self.temp.name),self.camera,6));worker.once()
        self.assertTrue(worker.stop.is_set());self.assertEqual(self.camera.calls,2)
    def test_plain_historical_timeout_not_promoted(self):
        self.camera.results=iter([ValueError('camera_timeout')]);self.worker.once()
        worker=configure(Collector(Store(self.temp.name),self.camera,6));worker.once()
        self.assertTrue(worker.stop.is_set());self.assertEqual(self.camera.calls,1)
        self.assertEqual(self.rows('capture_request_timeouts'),[])
    def test_pending_attempt_not_promoted(self):
        r.begin(self.store,1)
        worker=configure(Collector(Store(self.temp.name),self.camera,6));worker.once()
        self.assertTrue(worker.stop.is_set());self.assertEqual(self.camera.calls,0)
    def test_new_evidence_is_immutable(self):
        self.failed()
        for sql in ('DELETE FROM capture_request_timeouts','UPDATE capture_request_timeouts SET context_sha256=\'x\''):
            with self.assertRaises(sqlite3.IntegrityError),self.store.connect() as db:db.execute(sql)
    def test_reserved_policy_cannot_be_claimed_via_manual_route(self):
        self.failed()
        with self.store.connect() as db:
            review=r.continuation_review(db,1,self.worker.continuation_context())
            action=dict(action='accept-gap-and-continue',attempt_id=review['attempt_id'],review_sha256=review['review_sha256'],approval_reference=r.REQUEST_POLICY)
            with self.assertRaisesRegex(ValueError,'reserved_policy'):r.accept_continuation(db,1,self.worker.continuation_context(),action,self.camera.ready)

class RequestTransportTests(unittest.TestCase):
    def test_direct_and_url_timeout_are_typed_once(self):
        for error in (TimeoutError(),urllib.error.URLError(TimeoutError())):
            camera=Transport('http://127.0.0.1')
            with patch.object(camera.opener,'open',side_effect=error) as opened,self.assertRaises(r.RequestTimeout):camera.capture()
            self.assertEqual(opened.call_count,1)
    def test_bad_body_provenance_is_not_request_timeout(self):
        response=test_transfer_recovery.BodyTimeoutTransportTests().response();del response.headers['X-AIEdge-SHA256']
        camera=Transport('http://127.0.0.1')
        with patch.object(camera.opener,'open',return_value=response),self.assertRaises(ValueError) as caught:camera.capture()
        self.assertNotIsInstance(caught.exception,r.RequestTimeout)
        self.assertNotIsInstance(caught.exception,r.BodyTimeout)
    def test_real_socket_headers_timeout_no_second_post(self):
        posts=[];release=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                posts.append(self.path);self.rfile.read(int(self.headers['Content-Length']));release.wait(2)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            camera=Transport('http://127.0.0.1:'+str(server.server_port))
            with self.assertRaises(r.RequestTimeout):camera.capture(deadline=time.monotonic()+.2)
            self.assertEqual(posts,['/api/v1/capture'])
        finally:release.set();server.shutdown();server.server_close();thread.join(2)

if __name__=='__main__':unittest.main()
