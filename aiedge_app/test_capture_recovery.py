"""Synthetic captures only. Exercise real transport classification and ledger."""
import io,json,hashlib,tempfile,unittest,urllib.error
from unittest.mock import patch
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from capture import Camera,Collector,Store
import capture_recovery as recovery

class FakeCamera:
    origin='synthetic';calls=0
    def __init__(self,results):self.results=iter(results)
    def readiness(self):return {'state':'ready'}
    def capture(self):
        self.calls+=1;r=next(self.results)
        if isinstance(r,Exception):raise r
        blob=b'\xff\xd8synthetic-'+str(self.calls).encode()+b'\xff\xd9'
        return blob,{'X-AIEdge-Frame-Id':str(self.calls),'X-AIEdge-SHA256':hashlib.sha256(blob).hexdigest(),
                     'X-AIEdge-Captured-At':(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(seconds=self.calls*6)).isoformat(),
                     'X-AIEdge-Clock-Id':'synthetic-clock','X-AIEdge-Capture-Monotonic-Us':str(self.calls*6000000)}

class RecoveryTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def rows(self,table):
        with self.store.connect() as db:return db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
    def test_exact_http_rejection_is_typed_and_never_retried_inside_request(self):
        c=Camera('http://127.0.0.1:1')
        err=urllib.error.HTTPError(c.origin,503,'rejected',{},io.BytesIO(b'Frame is stale or clock changed during capture'))
        with patch.object(c.opener,'open',side_effect=err) as opened:
            with self.assertRaises(recovery.FreshnessRejected):c.capture()
            self.assertEqual(opened.call_count,1)
    def test_unknown_http_body_is_not_recoverable(self):
        c=Camera('http://127.0.0.1:1');err=urllib.error.HTTPError(c.origin,503,'reject',{},io.BytesIO(b'unknown'))
        with patch.object(c.opener,'open',side_effect=err):
            with self.assertRaises(ValueError) as caught:c.capture()
        self.assertNotIsInstance(caught.exception,recovery.FreshnessRejected)
    def test_failure_then_next_slot_is_new_capture_and_old_rows_stay_exact(self):
        c=FakeCamera([True,recovery.FreshnessRejected(),True]);worker=Collector(self.store,c,6)
        worker.once();before=self.rows('frames');worker.once()
        self.assertEqual(c.calls,2);self.assertFalse(worker.stop.is_set());self.assertEqual(worker.recovery_state,'waiting_for_next_slot')
        self.assertEqual(self.store.status()['captures'],1);self.assertEqual(len(self.rows('failures')),1)
        with self.store.connect() as db:self.assertTrue(recovery.publication_blocked(db,1))
        worker.once();self.assertEqual(c.calls,3);self.assertEqual(self.rows('frames')[:1],before)
        self.assertEqual([r[1] for r in self.rows('continuous_capture_outcomes')],['committed','rejected','committed'])
        self.assertEqual(self.rows('capture_failure_boundaries')[0][1:],(1,'camera_clock_changed','rejected'))
        with self.store.connect() as db:self.assertTrue(recovery.boundary(db,2));self.assertFalse(recovery.publication_blocked(db,2))
    def test_timeout_unknown_outcome_holds_across_process_restart_and_new_floor(self):
        c=FakeCamera([ValueError('camera_timeout'),True]);worker=Collector(self.store,c,6);worker.once();worker.once()
        self.assertEqual(c.calls,1);self.assertTrue(worker.stop.is_set())
        for floor in (1,2):
            next_worker=Collector(self.store,c,6,recovery_floor=floor);next_worker.once();self.assertTrue(next_worker.stop.is_set());self.assertEqual(c.calls,1)
    def test_bare_matching_error_string_does_not_authorize_retry(self):
        c=FakeCamera([ValueError('camera_clock_changed'),True]);worker=Collector(self.store,c,6);worker.once();worker.once()
        self.assertTrue(worker.stop.is_set());self.assertEqual(c.calls,1)
    def test_three_rejections_exhaust_budget_and_restart_cannot_reset_it(self):
        c=FakeCamera([recovery.FreshnessRejected() for _ in range(4)]);worker=Collector(self.store,c,6)
        for _ in range(4):worker.once()
        self.assertEqual(c.calls,3);self.assertTrue(worker.stop.is_set());self.assertEqual(worker.rejections,3)
        restarted=Collector(self.store,c,6);restarted.once();self.assertEqual(c.calls,3);self.assertTrue(restarted.stop.is_set())
    def test_success_does_not_reset_total_rejection_budget(self):
        c=FakeCamera([recovery.FreshnessRejected(),True,recovery.FreshnessRejected(),True,recovery.FreshnessRejected(),True]);worker=Collector(self.store,c,6)
        for _ in range(6):worker.once()
        self.assertEqual(c.calls,5);self.assertEqual(worker.rejections,3);self.assertTrue(worker.stop.is_set())
    def test_crashed_pending_attempt_holds_without_new_post(self):
        recovery.begin(self.store,1);c=FakeCamera([True]);worker=Collector(self.store,c,6);worker.once()
        self.assertEqual(c.calls,0);self.assertTrue(worker.stop.is_set())
    def test_intent_commit_failure_prevents_post(self):
        c=FakeCamera([True]);worker=Collector(self.store,c,6)
        with patch('capture_recovery.begin',side_effect=OSError('disk full')):worker.once()
        self.assertEqual(c.calls,0);self.assertTrue(worker.stop.is_set())
    def test_outcome_commit_failure_after_saved_photo_holds_and_preserves_photo(self):
        c=FakeCamera([True,True]);worker=Collector(self.store,c,6)
        with patch('capture_recovery.finish',side_effect=OSError('disk full')):worker.once()
        self.assertEqual(self.store.status()['captures'],1);worker.once();self.assertEqual(c.calls,1)
        self.assertTrue(Collector(self.store,c,6).stop.is_set())
    def test_failure_record_error_holds_no_automatic_repeat(self):
        c=FakeCamera([recovery.FreshnessRejected(),True]);worker=Collector(self.store,c,6)
        with patch.object(self.store,'fail',side_effect=OSError('disk full')):worker.once()
        worker.once();self.assertEqual(c.calls,1);self.assertTrue(worker.stop.is_set())
    def test_old_failure_is_preserved_without_poisoning_new_run(self):
        self.store.fail('camera_clock_changed');before=self.rows('failures');c=FakeCamera([True]);worker=Collector(self.store,c,6)
        worker.once();self.assertFalse(worker.stop.is_set());self.assertEqual(self.rows('failures'),before)
    def test_failure_boundary_corruption_is_rejected(self):
        self.store.fail('camera_clock_changed',outcome='rejected')
        with self.store.connect() as db:db.execute("UPDATE capture_failure_boundaries SET error='different'")
        with self.store.connect() as db:
            with self.assertRaisesRegex(ValueError,'boundary_invalid'):recovery.boundary(db,1)
    def test_normal_active_capture_keeps_previous_publication_but_crash_blocks_it(self):
        ident,_=recovery.begin(self.store,1)
        self.store.active_capture_attempt=None
        self.assertTrue(self.store.publication_blocked(0))
        self.store.active_capture_attempt=ident
        self.assertFalse(self.store.publication_blocked(0))
        self.store.active_capture_attempt=None
        self.assertTrue(self.store.publication_blocked(0))
    def test_status_has_bounded_durable_attempt_evidence(self):
        worker=Collector(self.store,FakeCamera([True]*12),6)
        for _ in range(12):worker.once()
        s=worker.recovery_status();self.assertEqual(s['attempt_count'],12)
        self.assertEqual(len(s['recent_attempts']),10);self.assertEqual(s['state'],'ready')
        self.assertEqual([a['event_id'] for a in s['recent_attempts']],list(range(3,13)))
        self.assertTrue(all(a['started_at'] and a['finished_at'] for a in s['recent_attempts']))

class NativeGapTests(unittest.TestCase):
    import test_consumption as fixtures
    setUp=fixtures.AccountingTests.setUp;tearDown=fixtures.AccountingTests.tearDown
    event=fixtures.AccountingTests.event;consume=fixtures.AccountingTests.consume;restart=fixtures.AccountingTests.restart
    def test_failure_starts_new_segment_and_restart_preserves_both(self):
        self.event(0);anchor=self.consume();self.event(1);first=self.consume()
        with self.store.connect() as db:old=list(db.execute('SELECT * FROM consumption_records ORDER BY event_id'))
        self.store.fail('camera_clock_changed',outcome='rejected');self.event(4);reset=self.consume()
        self.assertEqual(reset['state'],'anchored');self.assertEqual(reset['value'],0);self.assertEqual(reset['gap_reason'],'capture_failure')
        self.assertEqual(reset['prior_segment_id'],first['segment_id']);self.assertIsNone(reset['unresolved_gap']['delta'])
        self.event(5);last=self.consume();self.assertAlmostEqual(last['value'],1)
        self.assertEqual(self.restart(),last)
        with self.store.connect() as db:
            self.assertEqual(list(db.execute('SELECT * FROM consumption_records WHERE segment_id=? ORDER BY event_id',(anchor['segment_id'],))),old)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM failures').fetchone()[0],1)

class SelectorGapTests(unittest.TestCase):
    import test_event_recognition as fixtures
    def test_failed_boundary_forces_full_and_saved_request_rederives(self):
        f=self.fixtures.EventRecognitionTests();f.setUp()
        try:
            event,sha,_=f.complete(1000000);f.feedback(event,sha,'anchored')
            f.store.fail('camera_clock_changed',outcome='rejected')
            event,sha,_=f.complete(3000000)
            req=f.request(event);self.assertTrue(all(req['reader_observed']));self.assertEqual(req['timing']['reason'],'capture_failure')
            self.assertTrue(req['flags']['gap'])
        finally:f.tearDown()

class ReportingRecoveryTests(unittest.TestCase):
    def test_rejected_frame_then_full_anchor_then_positive_mqtt_value(self):
        from test_event_consumption import EventConsumptionTests
        from service import publication_state
        from mqtt_consumption import fresh_consumption
        f=EventConsumptionTests();f.setUp()
        try:
            f.recognize_consume(100.2);prior=f.recognize_consume(100.3);old=f.records()
            class CameraFixture:
                origin='fixture'
                def readiness(self):return {'state':'ready'}
                def capture(self):
                    if self.results[0] is None:self.results.pop(0);raise recovery.FreshnessRejected()
                    quantity,tick=self.results.pop(0);blob=b'\xff\xd8'+str(quantity).encode()+b'\xff\xd9'
                    return blob,{'X-AIEdge-Frame-Id':str(tick),'X-AIEdge-SHA256':hashlib.sha256(blob).hexdigest(),
                      'X-AIEdge-Captured-At':(f.start+timedelta(microseconds=tick)).isoformat(),
                      'X-AIEdge-Clock-Id':'test-a','X-AIEdge-Capture-Monotonic-Us':str(tick)}
            camera=CameraFixture();camera.results=[None,(101.4,4000000),(101.5,5000000)]
            collector=Collector(f.store,camera,6)
            collector.once()
            self.assertIsNone(fresh_consumption(publication_state(f.store,f.recognition,f.formats,f.worker),90))
            collector.once();self.assertTrue(f.recognition.once());anchor=f.consume()
            self.assertEqual(anchor['state'],'anchored');self.assertEqual(anchor['observation_support']['reader_observed'],[True]*3)
            self.assertEqual(anchor['gap_reason'],'capture_failure');self.assertEqual(anchor['prior_segment_id'],prior['segment_id'])
            self.assertIsNone(anchor['unresolved_gap']['delta'])
            self.assertEqual(fresh_consumption(publication_state(f.store,f.recognition,f.formats,f.worker),90)['value'],0)
            collector.once();self.assertTrue(f.recognition.once());accepted=f.consume()
            public=fresh_consumption(publication_state(f.store,f.recognition,f.formats,f.worker),90)
            self.assertAlmostEqual(public['value'],.1);self.assertEqual(public['event_id'],accepted['event_id'])
            self.assertEqual(public['coverage'],'observed_segment_only');self.assertIsNone(public['unresolved_gap']['delta'])
            self.assertEqual(f.records()[:2],old);self.assertEqual(f.store.status()['failures'],1)
            self.assertFalse(collector.stop.is_set());self.assertEqual(f.restart_consumption(),accepted)
        finally:f.tearDown()
