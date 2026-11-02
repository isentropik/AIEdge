"""Synthetic evidence only: explicit acceptance never resolves an unknown POST."""
import copy,json,sqlite3,tempfile,threading,time,unittest,urllib.request,urllib.error
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch
from capture import Store,Collector
from test_capture_recovery import FakeCamera
import capture_recovery as r

READY=dict(protocol_version=1,mode='remote-camera',state='ready',camera_available=True,
           settings_ready=True,clock_synchronized=True,capture_path='/api/v1/capture',
           capture_method='POST',capture_clock_metadata=True,image_sha256=True)

class Camera(FakeCamera):
    def __init__(self,results):
        super().__init__(results);self.probes=0;self.ready=copy.deepcopy(READY);self.lock=threading.RLock()
    @contextmanager
    def operation(self):
        if not self.lock.acquire(False):raise ValueError('camera_busy')
        try:yield
        finally:self.lock.release()
    def require_capture(self):pass
    def readiness(self):self.probes+=1;return copy.deepcopy(self.ready)

def configure(worker):
    worker.continuation_context=lambda:{'source':'synthetic-source','settings':'synthetic-settings'}
    return worker

def request(worker):
    review=worker.continuation_review()
    return dict(action='accept-gap-and-continue',attempt_id=review['attempt_id'],
                review_sha256=review['review_sha256'],approval_reference='synthetic-approval-only')

class ContinuationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
        self.camera=Camera([True,ValueError('camera_timeout'),True,True,ValueError('camera_timeout')])
        self.worker=configure(Collector(self.store,self.camera,6));self.worker.once();self.worker.once()
    def tearDown(self):self.temp.cleanup()
    def rows(self,table):
        with self.store.connect() as db:return db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
    def test_review_has_no_camera_io_or_writes(self):
        before=self.rows('continuous_capture_outcomes');probes=self.camera.probes
        review=self.worker.continuation_review()
        self.assertEqual(review['after_event_id'],1);self.assertIsNone(review['gap_delta'])
        self.assertTrue(review['unknown_outcome_preserved']);self.assertEqual(self.camera.calls,2)
        self.assertEqual(self.camera.probes,probes);self.assertEqual(self.rows('continuous_capture_outcomes'),before)
        self.assertEqual(self.rows('capture_continuations'),[])
    def test_acceptance_preserves_every_old_row_and_never_calls_capture(self):
        tables=('frames','capture_events','capture_clocks','failures','capture_failure_boundaries','continuous_capture_attempts','continuous_capture_outcomes')
        before={t:self.rows(t) for t in tables};images={p.name:p.read_bytes() for p in (self.store.root/'images').iterdir()}
        action=request(self.worker);self.worker.continue_after_gap(action)
        self.assertEqual(self.camera.calls,2);self.assertEqual(len(self.rows('capture_continuations')),1)
        for t,rows in before.items():self.assertEqual(self.rows(t),rows)
        self.assertEqual({p.name:p.read_bytes() for p in (self.store.root/'images').iterdir()},images)
        self.assertTrue(self.store.publication_blocked(1))
        self.worker.once()
        self.assertEqual(self.camera.calls,3);self.assertFalse(self.store.publication_blocked(2))
        self.assertEqual([x[1] for x in self.rows('continuous_capture_outcomes')],['committed','unknown','committed'])
        self.assertNotEqual(self.rows('continuous_capture_attempts')[-1][0],action['attempt_id'])
        with self.store.connect() as db:self.assertTrue(r.boundary(db,2))
        for t,rows in before.items():self.assertEqual(self.rows(t)[:len(rows)],rows)
    def test_duplicate_acceptance_is_rejected_without_second_probe_or_capture(self):
        action=request(self.worker);self.worker.continue_after_gap(action);probes=self.camera.probes
        with self.assertRaises(ValueError):self.worker.continue_after_gap(action)
        self.assertEqual(self.camera.probes,probes);self.assertEqual(self.camera.calls,2)
        self.assertEqual(len(self.rows('capture_continuations')),1)
    def test_restart_before_new_capture_retains_permission_and_old_unknown(self):
        self.worker.continue_after_gap(request(self.worker))
        restarted=configure(Collector(Store(self.temp.name),self.camera,6,recovery_floor=2))
        self.assertFalse(restarted.stop.is_set());self.assertTrue(self.store.publication_blocked(1))
        restarted.once();self.assertEqual(self.camera.calls,3)
        self.assertEqual(self.rows('continuous_capture_outcomes')[1][1],'unknown')
        self.assertEqual(restarted.recovery_status()['accepted_unknown_gaps'],1)
    def test_new_unknown_requires_its_own_review_and_holds_again(self):
        action=request(self.worker);self.worker.continue_after_gap(action)
        for _ in range(3):self.worker.once()
        self.assertTrue(self.worker.stop.is_set());self.assertTrue(self.store.publication_blocked(3))
        self.assertEqual(self.worker.recovery_status()['hold_reason'],'unknown_capture_outcome')
        new=request(self.worker);self.assertNotEqual(new['attempt_id'],action['attempt_id'])
        with self.assertRaisesRegex(ValueError,'review_changed'):self.worker.continue_after_gap(action)
        self.assertEqual(self.camera.calls,5)
    def test_changed_settings_invalidate_review(self):
        action=request(self.worker);self.worker.continuation_context=lambda:{'settings':'different'}
        with self.assertRaisesRegex(ValueError,'review_changed'):self.worker.continue_after_gap(action)
        self.assertEqual(self.rows('capture_continuations'),[])
    def test_changed_settings_during_readiness_invalidate_review(self):
        action=request(self.worker);original=self.camera.readiness
        def probe():self.worker.continuation_context=lambda:{'settings':'different'};return original()
        self.camera.readiness=probe
        with self.assertRaisesRegex(ValueError,'review_changed'):self.worker.continue_after_gap(action)
        self.assertTrue(self.worker.stop.is_set())
    def test_changed_historical_metadata_invalidate_review(self):
        action=request(self.worker)
        with self.store.connect() as db:db.execute("UPDATE frames SET received_at='different' WHERE rowid=1")
        with self.assertRaisesRegex(ValueError,'review_changed'):self.worker.continue_after_gap(action)
    def test_changed_ledger_during_readiness_invalidates_review(self):
        action=request(self.worker);original=self.camera.readiness
        def probe():self.store.fail('camera_connection_failed');return original()
        self.camera.readiness=probe
        with self.assertRaisesRegex(ValueError,'review_changed'):self.worker.continue_after_gap(action)
        self.assertEqual(self.rows('capture_continuations'),[])
    def test_pending_attempt_cannot_be_accepted(self):
        ident=self.rows('continuous_capture_attempts')[-1][0]
        with self.store.connect() as db:db.execute('DELETE FROM continuous_capture_outcomes WHERE attempt_id=?',(ident,))
        with self.assertRaisesRegex(ValueError,'pending_attempt'):self.worker.continuation_review()
    def test_multiple_unknowns_cannot_be_covered_by_one_action(self):
        with self.store.connect() as db:db.execute("UPDATE continuous_capture_outcomes SET outcome='unknown',event_id=NULL,error='camera_timeout' WHERE rowid=1")
        with self.assertRaisesRegex(ValueError,'one_latest_unknown'):self.worker.continuation_review()
    def test_partial_saved_event_is_not_a_transport_only_timeout(self):
        blob,headers=self.camera.capture();self.store.add(self.camera.origin,blob,headers)
        with self.assertRaisesRegex(ValueError,'saved_event_conflict'):self.worker.continuation_review()
    def test_non_timeout_unknown_does_not_qualify(self):
        with self.store.connect() as db:db.execute("UPDATE continuous_capture_outcomes SET error='camera_clock_changed' WHERE outcome='unknown'")
        with self.assertRaisesRegex(ValueError,'terminal_timeout'):self.worker.continuation_review()
    def test_missing_failure_boundary_refuses_acceptance(self):
        with self.store.connect() as db:db.execute('DELETE FROM capture_failure_boundaries')
        with self.assertRaisesRegex(ValueError,'failure_binding'):self.worker.continuation_review()
    def test_changed_bound_outcome_reinstates_fail_closed_behavior(self):
        self.worker.continue_after_gap(request(self.worker))
        with self.store.connect() as db:db.execute("UPDATE continuous_capture_outcomes SET finished_at='2026-01-01T00:00:00+00:00' WHERE outcome='unknown'")
        with self.store.connect() as db:
            with self.assertRaisesRegex(ValueError,'continuation_invalid'):r.readiness(db,1)
        with self.assertRaisesRegex(ValueError,'continuation_invalid'):self.store.publication_blocked(2)
    def test_acceptance_rows_are_append_only(self):
        self.worker.continue_after_gap(request(self.worker))
        for sql in ("UPDATE capture_continuations SET approval_reference='bad'",'DELETE FROM capture_continuations'):
            with self.store.connect() as db:
                with self.assertRaisesRegex(sqlite3.IntegrityError,'immutable'):db.execute(sql)
    def test_camera_not_ready_never_writes_acceptance(self):
        action=request(self.worker);self.camera.ready['state']='busy'
        with self.assertRaisesRegex(ValueError,'camera_not_ready'):self.worker.continue_after_gap(action)
        self.assertEqual(self.rows('capture_continuations'),[]);self.assertEqual(self.camera.calls,2)
    def test_failed_passive_probe_preserves_hold_and_has_no_new_capture_failure(self):
        action=request(self.worker);before=self.rows('failures')
        with patch.object(self.camera,'readiness',side_effect=ValueError('camera_connection_failed')):
            with self.assertRaises(ValueError):self.worker.continue_after_gap(action)
        self.assertEqual(self.rows('failures'),before);self.assertTrue(self.worker.stop.is_set())
    def test_invalid_request_or_missing_approval_reference_never_commits(self):
        for field,value in [('action','reset'),('attempt_id','bad'),('approval_reference',''),('approval_reference',True)]:
            action=request(self.worker);action[field]=value
            with self.assertRaises(ValueError):self.worker.continue_after_gap(action)
        self.assertEqual(self.rows('capture_continuations'),[]);self.assertEqual(self.camera.calls,2)
    def test_commit_failure_does_not_release_hold(self):
        action=request(self.worker)
        original=r.accept_continuation
        def fail(*args):original(*args);raise sqlite3.OperationalError('synthetic commit failure')
        with patch.object(r,'accept_continuation',side_effect=fail):
            with self.assertRaises(sqlite3.OperationalError):self.worker.continue_after_gap(action)
        self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.rows('capture_continuations'),[])
    def test_service_stop_cannot_be_cleared(self):
        action=request(self.worker);self.worker.request_stop()
        with self.assertRaisesRegex(ValueError,'held_collector'):self.worker.continue_after_gap(action)
        self.worker.once();self.assertEqual(self.camera.calls,2)
    def test_shutdown_during_probe_never_admits_continuation(self):
        action=request(self.worker);original=self.camera.readiness
        def probe():self.worker.request_stop();return original()
        self.camera.readiness=probe
        with self.assertRaisesRegex(ValueError,'stopping_or_active'):self.worker.continue_after_gap(action)
        self.assertEqual(self.rows('capture_continuations'),[])
    def test_healthy_collector_cannot_be_restarted_by_this_action(self):
        healthy=configure(Collector(Store(self.temp.name+'/healthy'),Camera([True]),6))
        with self.assertRaisesRegex(ValueError,'held_collector'):healthy.continuation_review()
    def test_one_existing_worker_parks_resumes_and_shuts_down(self):
        # Short synthetic interval; no camera or household I/O.
        self.worker.interval=.01
        thread=threading.Thread(target=self.worker.run);thread.start()
        try:
            time.sleep(.03);self.assertEqual(self.camera.calls,2);self.assertTrue(thread.is_alive())
            self.worker.continue_after_gap(request(self.worker))
            deadline=time.monotonic()+2
            while (self.camera.calls<5 or not self.worker.stop.is_set()) and time.monotonic()<deadline:time.sleep(.01)
            self.assertEqual(self.camera.calls,5);self.assertTrue(self.worker.stop.is_set())
            self.assertTrue(thread.is_alive())
        finally:self.worker.request_stop();thread.join(2)
        self.assertFalse(thread.is_alive())
    def test_acceptance_does_not_reset_rejection_allowance(self):
        with self.store.connect() as db:
            # A synthetic older streak directly preceding the unknown. It must
            # survive acceptance; production begin already blocks three in a row.
            db.execute("UPDATE continuous_capture_outcomes SET outcome='rejected',event_id=NULL,error=? WHERE rowid=1",(r.FRESHNESS,))
        self.worker.continue_after_gap(request(self.worker))
        with self.store.connect() as db:self.assertEqual(r.rejection_streak(db,99),(1,None))
        self.camera.results=iter([r.FreshnessRejected(),r.FreshnessRejected(),True])
        self.worker.once();self.worker.once();self.worker.once()
        self.assertEqual(self.camera.calls,4);self.assertTrue(self.worker.stop.is_set())
        self.assertEqual(self.worker.recovery_status()['consecutive_rejections'],3)
    def test_full_ledger_review_rejects_corrupt_older_commit(self):
        with self.store.connect() as db:db.execute('UPDATE continuous_capture_outcomes SET event_id=99 WHERE rowid=1')
        with self.assertRaisesRegex(ValueError,'ledger_invalid'):self.worker.continuation_review()
    def test_historical_three_rejections_cannot_be_bypassed_by_acceptance(self):
        # Deliberately malformed/imported history: the review must fail closed
        # even if a timeout intent somehow exists beyond an exhausted streak.
        with self.store.connect() as db:
            db.execute('DELETE FROM continuous_capture_outcomes');db.execute('DELETE FROM continuous_capture_attempts')
            for i in range(3):
                db.execute('INSERT INTO continuous_capture_attempts VALUES(?,?,?,?)',(str(i),1,1,'2026-01-01T00:00:00+00:00'))
                db.execute('INSERT INTO continuous_capture_outcomes VALUES(?,?,?,?,?)',(str(i),'rejected',None,r.FRESHNESS,'2026-01-01T00:00:01+00:00'))
        ident='last-timeout'
        from capture import now
        with self.store.connect() as db:db.execute('INSERT INTO continuous_capture_attempts VALUES(?,?,?,?)',(ident,1,1,now()))
        self.store.fail('camera_timeout',attempt=ident)
        with self.assertRaisesRegex(ValueError,'freshness_recovery_exhausted'):self.worker.continuation_review()
    def test_new_crashed_pending_blocks_even_with_prior_acceptance(self):
        self.worker.continue_after_gap(request(self.worker));ident,_=r.begin(self.store,1)
        self.store.active_capture_attempt=None
        with self.store.connect() as db:self.assertEqual(r.readiness(db,999)[0],'unknown_capture_outcome')
        self.assertTrue(self.store.publication_blocked(2))
        restarted=configure(Collector(Store(self.temp.name),self.camera,6))
        with self.assertRaisesRegex(ValueError,'pending_attempt'):restarted.continuation_review()
    def test_lifecycle_shutdown_drains_parked_collector(self):
        from lifecycle import ServiceRuntime
        class Server:
            def __init__(self):self.done=threading.Event()
            def serve_forever(self,**kwargs):self.done.wait(3)
            def shutdown(self):self.done.set()
            def server_close(self):pass
        runtime=ServiceRuntime(Server(),[self.worker],timeout=2)
        result=[];thread=threading.Thread(target=lambda:result.append(runtime.run()));thread.start()
        self.assertTrue(runtime.ready.wait(2));runtime.request_stop();thread.join(3)
        self.assertFalse(thread.is_alive());self.assertEqual(result,[True]);self.assertEqual(self.camera.calls,2)
    def test_saved_acceptance_lookup_survives_lost_response_and_restart(self):
        action=request(self.worker)
        with self.store.connect() as db:self.assertEqual(r.continuation_record(db,action['attempt_id'])['state'],'not_accepted')
        self.worker.continue_after_gap(action)
        reopened=Store(self.temp.name)
        with reopened.connect() as db:record=r.continuation_record(db,action['attempt_id'])
        self.assertEqual(record['state'],'gap_accepted');self.assertEqual(record['review_sha256'],action['review_sha256'])
        self.assertEqual(record['approval_reference'],action['approval_reference']);self.assertTrue(record['unknown_outcome_preserved'])
        self.assertEqual(self.camera.calls,2)

class ContinuationHttpTests(unittest.TestCase):
    def test_authenticated_explicit_action_only(self):
        from service import handler
        class Setup:
            meter=SimpleNamespace(status=lambda:{})
            edits=SimpleNamespace(status=lambda:{})
            def status(self):return {}
        with tempfile.TemporaryDirectory() as root:
            store=Store(root);camera=Camera([ValueError('camera_timeout'),True]);worker=configure(Collector(store,camera,6));worker.once()
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(store,False,worker,setup=Setup()))
            thread=threading.Thread(target=server.serve_forever);thread.start()
            base='http://127.0.0.1:'+str(server.server_port)
            def get(path):
                with urllib.request.urlopen(base+path,timeout=2) as response:return json.load(response)
            def post(action,token):
                req=urllib.request.Request(base+'/api/capture-continuation',data=json.dumps(action).encode(),headers={'Content-Type':'application/json','X-AIEdge-Setup':token})
                with urllib.request.urlopen(req,timeout=2) as response:return json.load(response)
            try:
                review=get('/api/capture-continuation');self.assertEqual(camera.calls,1)
                action=request(worker)
                with self.assertRaises(urllib.error.HTTPError) as denied:post(action,'wrong')
                self.assertEqual(denied.exception.code,403)
                token=get('/api/setup')['token']
                self.assertEqual(post(action,token)['state'],'gap_accepted');self.assertEqual(camera.calls,1)
                saved=get('/api/capture-continuation?attempt_id='+action['attempt_id'])
                self.assertEqual(saved['review_sha256'],review['review_sha256']);self.assertEqual(saved['state'],'gap_accepted')
                for query in ('?attempt_id=bad','?unexpected=1','?attempt_id='+action['attempt_id']+'&attempt_id='+action['attempt_id']):
                    with self.assertRaises(urllib.error.HTTPError):get('/api/capture-continuation'+query)
                with self.assertRaises(urllib.error.HTTPError):post(action,token)
                with store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM capture_continuations').fetchone()[0],1)
            finally:server.shutdown();server.server_close();thread.join(2)

class ContinuationAccountingTests(unittest.TestCase):
    def test_unknown_gap_full_anchor_and_same_event_publication(self):
        from test_event_consumption import EventConsumptionTests
        from service import publication_state
        from mqtt_consumption import fresh_consumption
        from datetime import timedelta
        import hashlib
        f=EventConsumptionTests();f.setUp()
        try:
            f.recognize_consume(100.2);prior=f.recognize_consume(100.3);old=f.records()
            class NativeCamera(Camera):
                def capture(self):
                    self.calls+=1;item=next(self.results)
                    if isinstance(item,Exception):raise item
                    quantity,tick=item;blob=b'\xff\xd8'+str(quantity).encode()+b'\xff\xd9'
                    return blob,{'X-AIEdge-Frame-Id':str(tick),'X-AIEdge-SHA256':hashlib.sha256(blob).hexdigest(),
                        'X-AIEdge-Captured-At':(f.start+timedelta(microseconds=tick)).isoformat(),
                        'X-AIEdge-Clock-Id':'test-a','X-AIEdge-Capture-Monotonic-Us':str(tick)}
            camera=NativeCamera([ValueError('camera_timeout'),(101.4,4000000),(101.5,5000000)])
            worker=configure(Collector(f.store,camera,6));worker.once()
            self.assertIsNone(fresh_consumption(publication_state(f.store,f.recognition,f.formats,f.worker),90))
            worker.continue_after_gap(request(worker))
            self.assertIsNone(fresh_consumption(publication_state(f.store,f.recognition,f.formats,f.worker),90))
            worker.once();self.assertTrue(f.recognition.once());anchor=f.consume()
            self.assertEqual(anchor['observation_support']['reader_observed'],[True]*3)
            self.assertEqual(anchor['gap_reason'],'capture_failure');self.assertEqual(anchor['prior_segment_id'],prior['segment_id'])
            self.assertIsNone(anchor['unresolved_gap']['delta']);self.assertEqual(anchor['value'],0)
            worker.once();self.assertTrue(f.recognition.once());accepted=f.consume()
            public=fresh_consumption(publication_state(f.store,f.recognition,f.formats,f.worker),90)
            self.assertEqual(public['event_id'],accepted['event_id']);self.assertAlmostEqual(public['value'],.1)
            self.assertEqual(public['coverage'],'observed_segment_only');self.assertIsNone(public['unresolved_gap']['delta'])
            self.assertEqual(f.records()[:2],old);self.assertEqual(f.restart_consumption(),accepted)
            with f.store.connect() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM continuous_capture_outcomes WHERE outcome='unknown'").fetchone()[0],1)
        finally:f.tearDown()
