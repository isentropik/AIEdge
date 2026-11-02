"""Synthetic passive-GET failures, durable boundaries and scheduled recovery."""
import errno,hashlib,sqlite3,ssl,tempfile,unittest,urllib.error
from datetime import timedelta
from unittest.mock import patch
from capture import Camera,Collector,Store
from camera_status import ReadinessTransportError
import capture_recovery as recovery
from test_capture_recovery import FakeCamera
from test_delivery_timing import Clock
from test_camera_status import fixture

class ReadinessRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
        self.camera=FakeCamera([True]*30);self.worker=Collector(self.store,self.camera,6)
    def tearDown(self):self.temp.cleanup()
    def rows(self,table):
        with self.store.connect() as db:return db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
    def fail_readiness(self,error=None):
        with patch.object(self.camera,'readiness',side_effect=error or ReadinessTransportError()):self.worker.once()
    def test_passive_failure_has_no_capture_intent_and_recovery_preserves_gap(self):
        self.worker.once();old=self.rows('capture_events');self.fail_readiness()
        self.assertEqual(self.camera.calls,1);self.assertEqual(len(self.rows('continuous_capture_attempts')),1)
        self.assertEqual(self.worker.recovery_status()['state'],'waiting_for_camera')
        self.assertFalse(self.worker.stop.is_set());failures=self.rows('failures')
        with self.store.connect() as db:self.assertTrue(recovery.publication_blocked(db,1))
        self.worker.once()
        self.assertEqual(self.camera.calls,2);self.assertEqual(self.rows('failures'),failures)
        self.assertEqual(self.rows('capture_events')[:1],old)
        with self.store.connect() as db:self.assertTrue(recovery.boundary(db,2))
        self.assertEqual(self.worker.recovery_status()['state'],'ready')
    def test_transient_os_errors_are_typed_only_by_passive_probe(self):
        camera=Camera('http://127.0.0.1:1')
        for error in (TimeoutError(),ConnectionRefusedError(),ConnectionResetError(),
                      OSError(errno.ENETUNREACH,'synthetic'),urllib.error.URLError(TimeoutError())):
            with self.subTest(error=type(error).__name__),patch.object(camera.opener,'open',side_effect=error) as opened:
                with self.assertRaises(ReadinessTransportError):camera.readiness()
                self.assertEqual(opened.call_count,1)
    def test_tls_auth_protocol_and_unclassified_failures_do_not_retry(self):
        camera=Camera('http://127.0.0.1:1')
        for error in (ssl.SSLError(errno.ECONNRESET,'synthetic'),
                      urllib.error.URLError(ssl.SSLCertVerificationError('synthetic')),
                      urllib.error.URLError('synthetic'),OSError(errno.EACCES,'synthetic')):
            with self.subTest(error=type(error).__name__),patch.object(camera.opener,'open',side_effect=error):
                with self.assertRaises(ValueError) as caught:camera.readiness()
                self.assertNotIsInstance(caught.exception,ReadinessTransportError)
        for code in ('camera_authentication_failed','camera_protocol_unsupported','camera_status_invalid','camera_connection_failed'):
            worker=Collector(self.store,self.camera,6)
            with patch.object(self.camera,'readiness',side_effect=ValueError(code)):worker.once()
            self.assertTrue(worker.stop.is_set())
        self.assertEqual(self.camera.calls,0)
    def test_same_typed_error_after_admission_is_unknown_and_holds(self):
        self.camera.results=iter([ReadinessTransportError(),True]);self.worker.once();self.worker.once()
        self.assertEqual(self.camera.calls,1);self.assertTrue(self.worker.stop.is_set())
        self.assertEqual(self.rows('continuous_capture_outcomes')[0][1],'unknown')
    def test_pending_request_blocks_passive_recovery(self):
        recovery.begin(self.store,1);self.fail_readiness()
        self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.camera.calls,0)
        self.assertEqual(self.worker.recovery_status()['hold_reason'],'unknown_capture_outcome')
    def test_unknown_outcome_survives_restart_and_context_change(self):
        self.camera.results=iter([ValueError('camera_timeout'),True]);self.worker.once()
        for floor in (1,2):
            worker=Collector(Store(self.temp.name),self.camera,6,recovery_floor=floor);worker.once()
            self.assertTrue(worker.stop.is_set());self.assertEqual(self.camera.calls,1)
    def test_failure_recording_error_holds(self):
        with patch.object(self.store,'fail',side_effect=sqlite3.OperationalError('synthetic')):self.fail_readiness()
        self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.camera.calls,0)
    def test_storage_failure_is_not_a_readiness_retry(self):
        with patch.object(self.store,'require_space',side_effect=ReadinessTransportError()):self.worker.once()
        self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.camera.calls,0)
    def test_device_nonready_status_remains_held(self):
        with patch.object(self.camera,'readiness',return_value={'state':'busy'}):self.worker.once()
        self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.camera.calls,0)
    def test_status_failure_does_not_replenish_freshness_streak(self):
        self.camera.results=iter([recovery.FreshnessRejected()]*3)
        self.worker.once();self.worker.once();self.fail_readiness()
        self.assertEqual(self.worker.recovery_status()['consecutive_rejections'],2)
        self.worker.once();self.assertTrue(self.worker.stop.is_set())
        self.assertEqual(self.worker.recovery_status()['consecutive_rejections'],3)
        self.assertEqual(self.camera.calls,3)
    def test_backoff_caps_and_success_resets_only_readiness_counter(self):
        delays=[]
        for _ in range(8):
            self.fail_readiness();delays.append(self.worker.readiness_retry_delay)
        self.assertEqual(delays,[6,12,24,48,60,60,60,60])
        self.assertEqual(len(self.rows('failures')),8);self.assertEqual(self.camera.calls,0)
        self.worker.once();self.assertEqual(self.worker.readiness_retry_delay,0)
        self.assertEqual(self.worker.readiness_failures,0);self.assertEqual(len(self.rows('failures')),8)
    def test_scheduler_waits_without_bursting_and_respects_larger_interval(self):
        for interval in (6,30,120):
            with self.subTest(interval=interval),tempfile.TemporaryDirectory() as directory:
                store=Store(directory);camera=FakeCamera([True]);worker=Collector(store,camera,interval)
                clock=Clock();starts=[];waits=[]
                def probe():
                    starts.append(clock.value);clock.advance(5)
                    if len(starts)<=3:raise ReadinessTransportError()
                    return {'state':'ready'}
                def wait(delay):
                    waits.append(delay);clock.advance(delay)
                    if len(starts)==4:worker.stop.set()
                with patch.object(camera,'readiness',side_effect=probe),patch('capture.time.monotonic',clock),patch.object(worker.stop,'wait',side_effect=wait):worker.run()
                self.assertEqual([b-a for a,b in zip(starts,starts[1:])],[max(interval,d) for d in (6,12,24)])
                self.assertEqual(camera.calls,1)
                with store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM continuous_capture_attempts').fetchone()[0],1)
                self.assertTrue(all(d>=0 for d in waits))
    def test_user_shutdown_interrupts_retry_wait(self):
        waits=[]
        def wait(delay):waits.append(delay);self.worker.stop.set()
        with patch.object(self.camera,'readiness',side_effect=ReadinessTransportError()),patch.object(self.worker.stop,'wait',side_effect=wait):self.worker.run()
        self.assertEqual(len(waits),1);self.assertEqual(self.camera.calls,0)
        self.assertEqual(len(self.rows('failures')),1)
    def test_readiness_overrun_does_not_reuse_previous_attempt_identity(self):
        self.worker.once();self.assertIsNotNone(self.worker.last_cycle_attempt)
        self.fail_readiness();self.assertIsNone(self.worker.last_cycle_attempt)
    def test_loopback_next_ready_response_creates_one_new_post(self):
        with fixture() as (camera,device),tempfile.TemporaryDirectory() as directory:
            store=Store(directory);worker=Collector(store,camera,6)
            with patch.object(camera.opener,'open',side_effect=urllib.error.URLError(TimeoutError())):worker.once()
            self.assertFalse(worker.stop.is_set());self.assertEqual(device.posts,0)
            worker.once();self.assertEqual((device.gets,device.posts),(1,1))
            self.assertEqual(store.status()['captures'],1);self.assertEqual(store.status()['failures'],1)
    def test_restart_retains_original_failure_and_does_not_rewrite_rows(self):
        self.fail_readiness();tables=('failures','capture_failure_boundaries','continuous_capture_attempts','continuous_capture_outcomes')
        old={table:self.rows(table) for table in tables}
        restarted=Collector(Store(self.temp.name),self.camera,6,recovery_floor=2);restarted.once()
        for table,rows in old.items():self.assertEqual(self.rows(table)[:len(rows)],rows)
        self.assertEqual(self.camera.calls,1)
    def test_passive_timeout_then_fresh_capture_reports_only_new_segment_usage(self):
        from test_event_consumption import EventConsumptionTests
        from service import publication_state
        from mqtt_consumption import fresh_consumption
        f=EventConsumptionTests();f.setUp()
        try:
            f.recognize_consume(100.2);prior=f.recognize_consume(100.3);old=f.records()
            class CameraFixture:
                origin='fixture';probes=0;posts=0
                results=[(101.4,4000000),(101.5,5000000)]
                def readiness(self):
                    self.probes+=1
                    if self.probes==1:raise ReadinessTransportError()
                    return {'state':'ready'}
                def capture(self):
                    self.posts+=1;quantity,tick=self.results.pop(0);blob=b'\xff\xd8'+str(quantity).encode()+b'\xff\xd9'
                    return blob,{'X-AIEdge-Frame-Id':str(tick),'X-AIEdge-SHA256':hashlib.sha256(blob).hexdigest(),
                        'X-AIEdge-Captured-At':(f.start+timedelta(microseconds=tick)).isoformat(),
                        'X-AIEdge-Clock-Id':'test-a','X-AIEdge-Capture-Monotonic-Us':str(tick)}
            camera=CameraFixture();collector=Collector(f.store,camera,6);collector.once()
            self.assertEqual(camera.posts,0);self.assertFalse(collector.stop.is_set())
            self.assertIsNone(fresh_consumption(publication_state(f.store,f.recognition,f.formats,f.worker),90))
            collector.once();self.assertTrue(f.recognition.once());anchor=f.consume()
            self.assertEqual(anchor['state'],'anchored');self.assertEqual(anchor['value'],0)
            self.assertEqual(anchor['gap_reason'],'capture_failure');self.assertEqual(anchor['prior_segment_id'],prior['segment_id'])
            self.assertIsNone(anchor['unresolved_gap']['delta'])
            collector.once();self.assertTrue(f.recognition.once());accepted=f.consume()
            public=fresh_consumption(publication_state(f.store,f.recognition,f.formats,f.worker),90)
            self.assertAlmostEqual(public['value'],.1);self.assertEqual(public['event_id'],accepted['event_id'])
            self.assertEqual(public['coverage'],'observed_segment_only');self.assertIsNone(public['unresolved_gap']['delta'])
            self.assertEqual(f.records()[:2],old);self.assertEqual(camera.posts,2)
            self.assertEqual(f.store.status()['failures'],1);self.assertEqual(f.restart_consumption(),accepted)
        finally:f.tearDown()

class Dev40ReadinessTests(unittest.TestCase):
    def test_accepted_unknowns_and_readiness_failure_survive_upgrade_startup(self):
        from test_capture_continuation import Camera,configure,request
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            camera=Camera([True,ValueError('camera_timeout'),True,ValueError('camera_timeout'),True])
            worker=configure(Collector(store,camera,6))
            for _ in range(2):
                worker.once();worker.once();worker.continue_after_gap(request(worker))
            with patch.object(camera,'readiness',side_effect=ReadinessTransportError()):worker.once()
            tables=('failures','capture_failure_boundaries','capture_continuations','continuous_capture_attempts','continuous_capture_outcomes')
            def rows():
                with store.connect() as db:return {t:db.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall() for t in tables}
            old=rows()
            restarted=configure(Collector(Store(directory),camera,6,recovery_floor=3));restarted.once()
            self.assertEqual(camera.calls,5);self.assertEqual(restarted.recovery_status()['state'],'ready')
            self.assertEqual(restarted.recovery_status()['accepted_unknown_gaps'],2)
            for table,records in old.items():self.assertEqual(rows()[table][:len(records)],records)
            self.assertEqual([r[1] for r in rows()['continuous_capture_outcomes']].count('unknown'),2)
            with store.connect() as db:self.assertTrue(recovery.boundary(db,3))

    def test_new_unknown_after_readiness_recovery_keeps_dev40_hold(self):
        from test_capture_continuation import Camera,configure,request
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);camera=Camera([ValueError('camera_timeout'),ValueError('camera_timeout')])
            worker=configure(Collector(store,camera,6));worker.once();worker.continue_after_gap(request(worker))
            with patch.object(camera,'readiness',side_effect=ReadinessTransportError()):worker.once()
            self.assertEqual(worker.recovery_status()['state'],'waiting_for_camera')
            worker.once();worker.once()
            self.assertEqual(camera.calls,2);self.assertTrue(worker.stop.is_set())
            self.assertEqual(worker.recovery_status()['state'],'held')
            self.assertEqual(worker.recovery_status()['hold_reason'],'unknown_capture_outcome')
            self.assertEqual(worker.recovery_status()['accepted_unknown_gaps'],1)

    def test_shutdown_interrupts_real_retry_wait_and_cannot_resume(self):
        import threading
        from test_capture_continuation import Camera
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);camera=Camera([True]);worker=Collector(store,camera,6)
            entered=threading.Event();original=worker.stop.wait
            def wait(delay):entered.set();return original(delay)
            with patch.object(camera,'readiness',side_effect=ReadinessTransportError()),patch.object(worker.stop,'wait',side_effect=wait):
                thread=threading.Thread(target=worker.run);thread.start()
                try:
                    self.assertTrue(entered.wait(3));worker.request_stop();thread.join(3)
                    self.assertFalse(thread.is_alive());worker.once();self.assertEqual(camera.calls,0)
                    self.assertEqual(store.status()['failures'],1)
                finally:worker.request_stop();thread.join(3)

    def test_new_pending_attempt_during_backoff_blocks_admission(self):
        from test_capture_continuation import Camera
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);camera=Camera([True]);worker=Collector(store,camera,6)
            with patch.object(camera,'readiness',side_effect=ReadinessTransportError()):worker.once()
            pending,_=recovery.begin(store,1)
            worker.once()
            self.assertEqual(camera.calls,0);self.assertTrue(worker.stop.is_set())
            self.assertEqual(worker.recovery_status()['hold_reason'],'unknown_capture_outcome')
            with store.connect() as db:
                self.assertEqual(db.execute('SELECT attempt_id FROM continuous_capture_attempts').fetchall(),[(pending,)])
                self.assertEqual(db.execute('SELECT COUNT(*) FROM continuous_capture_outcomes').fetchone()[0],0)
