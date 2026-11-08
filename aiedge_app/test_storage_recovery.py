"""Synthetic storage failures: no lost request becomes measured gas."""
import tempfile,unittest
from unittest.mock import patch
from capture import Store,Collector,StorageLowSpace
from test_capture_continuation import Camera,configure
import capture_recovery as r

class StorageRecoveryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
  self.camera=Camera([True,True,True,True]);self.worker=configure(Collector(self.store,self.camera,6))
 def tearDown(self):self.temp.cleanup()
 def rows(self,t):
  with self.store.connect() as db:return db.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall()
 def fail_after_capture(self):
  self.worker.once()
  with patch.object(self.store,'add',side_effect=StorageLowSpace()):self.worker.once()
 def test_mid_capture_failure_preserved_and_new_capture_after_recovery(self):
  self.fail_after_capture();before={t:self.rows(t) for t in ('frames','failures','capture_failure_boundaries','continuous_capture_outcomes')}
  self.assertEqual(self.worker.recovery_status()['state'],'waiting_for_storage')
  self.worker.once();self.assertEqual(self.camera.calls,2)
  self.assertEqual(self.rows('storage_continuations')[0][4],r.STORAGE_POLICY)
  self.assertTrue(self.store.publication_blocked(1))
  self.worker.once();self.assertEqual(self.camera.calls,3)
  for t,v in before.items():self.assertEqual(self.rows(t)[:len(v)],v)
  with self.store.connect() as db:self.assertTrue(r.boundary(db,2))
 def test_low_space_wait_does_not_contact_camera_or_grow_ledger(self):
  self.fail_after_capture();probes=self.camera.probes;failures=self.rows('failures')
  with patch.object(self.store,'storage_status',return_value={'state':'low_space'}):
   for _ in range(20):self.worker.once()
  self.assertEqual(self.camera.probes,probes);self.assertEqual(self.camera.calls,2)
  self.assertEqual(self.rows('failures'),failures);self.assertGreaterEqual(self.worker.readiness_retry_delay,30)
 def test_pre_request_failure_resumes_without_acceptance_or_capture_replay(self):
  with patch.object(self.store,'require_space',side_effect=StorageLowSpace()):self.worker.once()
  self.assertEqual(self.camera.calls,0);self.assertFalse(self.worker.stop.is_set())
  self.worker.once();self.assertEqual(self.camera.calls,1)
  self.assertEqual(self.rows('storage_continuations'),[])
  with self.store.connect() as db:self.assertTrue(r.boundary(db,1))
 def test_restart_recovers_durable_storage_unknown(self):
  self.fail_after_capture();self.worker=configure(Collector(Store(self.temp.name),self.camera,6,recovery_floor=2))
  self.assertFalse(self.worker.stop.is_set());self.worker.once();self.worker.once()
  self.assertEqual(self.camera.calls,3);self.assertEqual(self.rows('continuous_capture_outcomes')[1][1],'unknown')
 def test_later_hard_failure_blocks_restart(self):
  self.fail_after_capture();self.store.fail('database_failure')
  restarted=configure(Collector(self.store,self.camera,6));self.assertTrue(restarted.stop.is_set())
 def test_pending_request_never_recovers(self):
  r.begin(self.store,1);restarted=configure(Collector(self.store,self.camera,6))
  restarted.once();self.assertTrue(restarted.stop.is_set());self.assertEqual(self.camera.calls,0)
 def test_space_drops_during_recovery_preserves_original_boundary(self):
  self.fail_after_capture();before=self.rows('failures');require=self.store.require_space;calls=[]
  def check(*args):
   calls.append(1)
   if len(calls)>1:raise StorageLowSpace()
   return require(*args)
  with patch.object(self.store,'require_space',side_effect=check):self.worker.once()
  self.assertEqual(self.rows('failures'),before);self.assertFalse(self.worker.stop.is_set())
  self.worker.once();self.worker.once();self.assertEqual(self.camera.calls,3)
 def test_busy_readiness_only_probes_after_space_returns(self):
  self.fail_after_capture();self.camera.ready['state']='busy';self.worker.once()
  self.assertEqual(self.camera.calls,2);self.assertEqual(self.rows('storage_continuations'),[])
 def test_context_change_during_probe_does_not_accept(self):
  self.fail_after_capture();original=self.camera.readiness
  def changed():self.worker.continuation_context=lambda:{'changed':True};return original()
  with patch.object(self.camera,'readiness',side_effect=changed):self.worker.once()
  self.assertEqual(self.rows('storage_continuations'),[]);self.assertTrue(self.worker.stop.is_set())
 def test_shutdown_never_resumes(self):
  self.fail_after_capture();self.worker.request_stop();self.worker.once()
  self.assertEqual(self.camera.calls,2);self.assertEqual(self.rows('storage_continuations'),[])
 def test_policy_cannot_be_requested_as_manual_approval(self):
  self.fail_after_capture()
  with self.store.connect() as db:
   review=r.storage_review(db,1,self.worker.continuation_context(),self.worker.storage_attempt)
   req=dict(action='accept-gap-and-continue',attempt_id=review['attempt_id'],review_sha256=review['review_sha256'],approval_reference=r.STORAGE_POLICY)
   with self.assertRaisesRegex(ValueError,'reserved_policy'):r.accept_continuation(db,1,self.worker.continuation_context(),req,self.camera.ready)


 def test_restart_after_storage_acceptance_preserves_unknown(self):
  self.fail_after_capture();self.worker.once()
  restarted=configure(Collector(Store(self.temp.name),self.camera,6,recovery_floor=2))
  restarted.once();self.assertEqual(self.camera.calls,3)
  self.assertEqual(self.rows('continuous_capture_outcomes')[1][1],'unknown')
 def test_database_failure_commit_stays_held(self):
  import sqlite3
  with patch.object(self.store,'require_space',side_effect=StorageLowSpace()),patch.object(self.store,'fail',side_effect=sqlite3.OperationalError('full')):self.worker.once()
  self.assertTrue(self.worker.stop.is_set());self.assertEqual(self.camera.calls,0)
 def test_storage_unavailable_does_not_probe(self):
  self.fail_after_capture();probes=self.camera.probes
  with patch.object(self.store,'storage_status',return_value={'state':'unavailable'}):self.worker.once()
  self.assertEqual(self.camera.probes,probes);self.assertEqual(self.camera.calls,2)

 def test_storage_wait_preserves_pending_typed_timeout_recovery(self):
  self.camera.results=iter([r.RequestTimeout(),True])
  self.worker.once();before=self.rows('failures')
  with patch.object(self.store,'require_space',side_effect=StorageLowSpace()):self.worker.once()
  self.assertEqual(self.worker.recovery_status()['state'],'waiting_for_storage')
  self.assertEqual(self.rows('failures'),before)
  self.worker.once();self.worker.once();self.assertEqual(self.camera.calls,2)
  self.assertEqual(self.rows('continuous_capture_outcomes')[0][1],'unknown')

 def test_storage_acceptance_immutable_and_not_in_legacy_timeout_table(self):
  import sqlite3
  self.fail_after_capture();self.worker.once()
  self.assertEqual(self.rows('capture_continuations'),[])
  with self.store.connect() as db:
   with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM storage_continuations')
  self.assertEqual(len(self.rows('storage_continuations')),1)

class StorageAccountingTests(unittest.TestCase):
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
            camera=NativeCamera([StorageLowSpace(),(101.4,4000000),(101.5,5000000)])
            worker=configure(Collector(f.store,camera,6));worker.once()
            self.assertIsNone(fresh_consumption(publication_state(f.store,f.recognition,f.formats,f.worker),90))
            worker.once()
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

if __name__=='__main__':unittest.main()
