import tempfile,unittest,sqlite3
from unittest.mock import patch
from capture import Store,Collector
from test_capture_continuation import Camera,configure
from camera_status import ReadinessTransportError
import capture_recovery as r

class InterruptionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name);self.camera=Camera([True]*10)
  self.worker=configure(Collector(self.store,self.camera,6));self.worker.once()
  self.ident,_=r.begin(self.store,1)
 def tearDown(self):self.tmp.cleanup()
 def rows(self,t):
  with self.store.connect() as db:return db.execute('SELECT * FROM '+t+' ORDER BY rowid').fetchall()
 def restart(self):return configure(Collector(Store(self.tmp.name),self.camera,6))
 def test_seals_append_only_and_new_capture_preserves_gap(self):
  before={t:self.rows(t) for t in ('frames','capture_events','capture_clocks','continuous_capture_attempts','continuous_capture_outcomes')}
  w=self.restart();calls=self.camera.calls;probes=self.camera.probes
  w.recover_interrupted_startup()
  self.assertEqual((calls,probes),(self.camera.calls,self.camera.probes));self.assertFalse(w.stop.is_set())
  self.assertEqual(self.rows('continuous_capture_outcomes')[-1][1:4],('unknown',None,'capture_interrupted'))
  w.once();self.assertEqual(self.camera.calls,calls)
  w.once();self.assertEqual(self.camera.calls,calls+1)
  for t,v in before.items():self.assertEqual(self.rows(t)[:len(v)],v)
  with self.store.connect() as db:self.assertTrue(r.boundary(db,2));self.assertFalse(r.publication_blocked(db,2))
  self.assertEqual(self.rows('capture_continuations')[-1][4],r.INTERRUPTION_POLICY)
 def test_live_owned_attempt_not_sealed(self):
  self.worker.stop.set();self.worker.recovery_state='held';self.worker.recover_interrupted_startup()
  self.assertEqual(len(self.rows('continuous_capture_outcomes')),1);self.assertEqual(self.rows('capture_interruptions'),[])
 def test_busy_and_transport_loss_never_replay(self):
  w=self.restart();w.recover_interrupted_startup();self.camera.ready['state']='busy';w.once()
  with patch.object(self.camera,'readiness',side_effect=ReadinessTransportError()):w.once()
  self.assertEqual(self.camera.calls,1);self.assertEqual(self.rows('capture_continuations'),[])
  w=self.restart();self.camera.ready['state']='ready';w.once();self.assertEqual(self.camera.calls,1);w.once();self.assertEqual(self.camera.calls,2)
 def test_restart_after_sealing_and_acceptance(self):
  w=self.restart();w.recover_interrupted_startup();w=self.restart();w.once();w=self.restart();w.once()
  self.assertEqual(self.camera.calls,2);self.assertEqual(len(self.rows('capture_interruptions')),1);self.assertEqual(len(self.rows('capture_continuations')),1)
 def test_saved_event_conflict_stays_held(self):
  blob,headers=self.camera.capture();self.store.add(self.camera.origin,blob,headers)
  w=self.restart();w.recover_interrupted_startup();self.assertTrue(w.stop.is_set());self.assertEqual(self.rows('capture_interruptions'),[])
 def test_multiple_pending_stays_held(self):
  with self.store.connect() as db:db.execute('INSERT INTO continuous_capture_attempts VALUES(?,?,?,?)',('b'*32,1,1,self.rows('continuous_capture_attempts')[-1][3]))
  w=self.restart();w.recover_interrupted_startup();self.assertTrue(w.stop.is_set());self.assertEqual(self.rows('capture_interruptions'),[])
 def test_later_hard_fault_stays_held(self):
  self.store.fail('camera_authentication_failed');w=self.restart();w.recover_interrupted_startup();self.assertTrue(w.stop.is_set());self.assertEqual(self.rows('capture_interruptions'),[])
 def test_context_change_before_readiness_stays_held(self):
  w=self.restart();w.recover_interrupted_startup();w.continuation_context=lambda:{'changed':True};probes=self.camera.probes;w.once();self.assertTrue(w.stop.is_set());self.assertEqual(self.camera.probes,probes)
 def test_shutdown_never_rearms(self):
  w=self.restart();w.request_stop();w.recover_interrupted_startup();w.once();self.assertEqual(self.camera.calls,1);self.assertEqual(self.rows('capture_interruptions'),[])
 def test_failed_write_rolls_back_all_interruption_rows(self):
  w=self.restart()
  with patch('capture_recovery.finish_transaction',side_effect=sqlite3.OperationalError('synthetic')):w.recover_interrupted_startup()
  self.assertTrue(w.stop.is_set());self.assertEqual(self.rows('capture_interruptions'),[]);self.assertEqual(self.rows('failures'),[]);self.assertEqual(len(self.rows('continuous_capture_outcomes')),1)
 def test_marker_immutable(self):
  w=self.restart();w.recover_interrupted_startup()
  for sql in ('DELETE FROM capture_interruptions','UPDATE capture_interruptions SET context_sha256="bad"'):
   with self.assertRaises(sqlite3.IntegrityError):
    with self.store.connect() as db:db.execute(sql)
 def test_unknown_after_later_event_not_accepted(self):
  w=self.restart();w.recover_interrupted_startup();blob,headers=self.camera.capture();self.store.add(self.camera.origin,blob,headers);w.once()
  self.assertTrue(w.stop.is_set());self.assertEqual(self.rows('capture_continuations'),[])
if __name__=='__main__':unittest.main()
