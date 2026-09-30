"""Synthetic quantities/clock metadata; no image labels or accuracy claims."""
import copy,hashlib,json,os,sqlite3,tempfile,threading,unittest
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import patch
from capture import Store,now
from recognition import Recognition
from reading_format import FormatStore,validate,display_quantity
from consumption import Consumption
from accounting_native import AccountingNative

PIPELINE='a'*64
LIBRARY=os.environ.get('AIEDGE_ACCOUNTING_LIBRARY')
def document(scales=(1000,5),errors=(.1,.1),rate=.05):
    result={'version':1,'pipeline_id':PIPELINE,'unit':'ft3','dials':[{'index':i,'value_per_revolution':period,'position_error':errors[i]} for i,period in enumerate(scales)]}
    if rate is not None:result['maximum_rate_per_second']=rate
    return result

class FormatBoundTests(unittest.TestCase):
    def test_absent_and_null_bound_keep_existing_identity(self):
        value=document(rate=None);canonical,identity=validate(value)
        value['maximum_rate_per_second']=None
        self.assertEqual(validate(value),(canonical,identity))
    def test_invalid_rate_is_rejected(self):
        for rate in (-1,True,float('nan'),float('inf'),10**400,'1'):
            with self.subTest(rate=rate),self.assertRaisesRegex(ValueError,'invalid_maximum_rate'):validate(document(rate=rate))
    def test_relative_quantity_does_not_wrap_or_pad_as_register(self):
        self.assertEqual(display_quantity(1001.25,document()),'1001.25')
        self.assertEqual(display_quantity(0,document()),'0.00')

@unittest.skipUnless(LIBRARY,'accounting native library required')
class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name)
        self.reader=SimpleNamespace(pipeline_id=PIPELINE,dials=[{'name':'Large'},{'name':'Small'}])
        self.recognition=Recognition(self.store,self.reader);self.formats=FormatStore(self.temp.name,self.recognition)
        self.saved=self.formats.save(document(),None)
        self.worker=Consumption(self.store,self.recognition,self.formats,LIBRARY)
        self.tick=1000000;self.counter=0
    def tearDown(self):
        self.worker._drop();self.temp.cleanup()
    def event(self,quantity,tick=None,boot='boot-a',camera='fixture',utc_jump=0,rejected=False,pending=False,clock=True,duplicate=False):
        self.counter+=1
        if tick is None:tick=self.tick
        self.tick=tick+30000000
        phases=[(quantity%p)/p*10 for p in (1000,5)]
        # Deliberately synthetic JPEG envelopes for ledger tests, not decodable photographs.
        blob=b'\xff\xd8'+(b'stationary' if duplicate else str(self.counter).encode())+b'\xff\xd9'
        digest=hashlib.sha256(blob).hexdigest();stamp=(datetime(2026,9,29,tzinfo=timezone.utc)+timedelta(microseconds=tick,seconds=utc_jump)).isoformat()
        headers={'X-AIEdge-Frame-Id':f'frame-{self.counter}','X-AIEdge-Captured-At':stamp,'X-AIEdge-SHA256':digest}
        if clock:headers.update({'X-AIEdge-Clock-Id':boot,'X-AIEdge-Capture-Monotonic-Us':str(tick)})
        self.store.add(camera,blob,headers)
        result={'state':'rejected' if rejected else 'estimated','pipeline_id':PIPELINE,'source_sha256':digest,
                'dial_positions':[{'state':'estimated','position':position} for position in phases],
                'training_allowed':False,'accuracy_verified':False}
        if not pending:
            with self.store.connect() as db:db.execute('INSERT OR IGNORE INTO inference VALUES(?,?,?,?)',(digest,PIPELINE,now(),json.dumps(result)))
        return digest
    def consume(self):
        self.assertTrue(self.worker.once());return self.worker.status()
    def restart(self):
        self.worker._drop();self.worker=Consumption(self.store,self.recognition,self.formats,LIBRARY)
        while self.worker.once():pass
        return self.worker.status()
    def test_empty_capture_ledger_waits_for_image_instead_of_recovering_forever(self):
        self.assertFalse(self.worker.once());self.assertEqual(self.worker.status()['state'],'waiting_for_image')
        self.assertEqual(self.restart()['state'],'waiting_for_image')
        self.event(0);self.assertEqual(self.consume()['state'],'anchored')
    def test_unique_intervals_and_many_turns_survive_restart(self):
        self.event(0);self.assertEqual(self.consume()['state'],'anchored')
        for amount in range(1,41):
            self.event(amount);state=self.consume();self.assertEqual(state['state'],'estimated');self.assertAlmostEqual(state['value'],amount)
        self.assertAlmostEqual(state['average_rate_per_second'],1/30)
        self.assertEqual(self.restart(),state)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM consumption_records').fetchone()[0],41)
    def test_same_image_still_records_distinct_timing_events_without_noise_consumption(self):
        self.event(12,duplicate=True);self.consume()
        for _ in range(3):self.event(12,duplicate=True);state=self.consume()
        self.assertEqual(self.store.status()['unique_images'],1)
        self.assertEqual(self.store.status()['captures'],4)
        self.assertEqual(state['state'],'within_noise');self.assertEqual(state['minimum'],0);self.assertIsNone(state['value'])
        self.assertEqual(self.restart(),state)
    def test_wrap_is_forward_and_not_sum_of_positive_noise(self):
        self.event(999.8);self.consume();self.event(1000.2);state=self.consume()
        self.assertEqual(state['state'],'estimated');self.assertAlmostEqual(state['value'],.4)
        for amount in (1000.18,1000.22,1000.18,1000.2):self.event(amount);state=self.consume()
        self.assertEqual(state['state'],'bounded');self.assertIsNone(state['value'])
        self.assertLess(state['minimum'],.4);self.assertGreater(state['maximum'],.42)
        self.assertEqual(self.restart(),state)
    def test_small_backward_estimate_is_withheld_not_clamped_and_replays_exactly(self):
        self.event(0);self.consume();self.event(1);self.assertEqual(self.consume()['value'],1)
        self.event(.99);state=self.consume();self.assertEqual(state['state'],'bounded');self.assertIsNone(state['value'])
        self.assertLess(state['minimum'],1);self.assertGreater(state['maximum'],1)
        self.assertEqual(self.restart(),state)
        self.event(1.01);state=self.consume();self.assertAlmostEqual(state['value'],1.01)
        self.event(.98);state=self.consume();self.assertEqual(state['state'],'bounded');self.assertIsNone(state['value'])
        self.assertEqual(self.restart(),state)
    def test_ambiguous_gap_and_no_rate_bound_never_invent_complete_turns(self):
        self.event(0);self.consume();self.event(0,tick=301000000);state=self.consume()
        self.assertEqual(state['state'],'ambiguous');self.assertIsNone(state['value'])
        original=state['segment_id']
        self.formats.save(document(rate=None),self.saved['revision']);self.assertTrue(self.worker.once())
        self.assertNotEqual(self.worker.status()['segment_id'],original)
        self.event(1);state=self.consume();self.assertEqual(state['state'],'ambiguous');self.assertTrue(state['upper_unbounded']);self.assertIsNone(state['maximum'])
    def test_rejected_observation_does_not_advance_physical_anchor(self):
        self.event(0);self.consume();self.event(.5,rejected=True);self.assertEqual(self.consume()['state'],'unavailable')
        self.event(1);state=self.consume();self.assertAlmostEqual(state['value'],1);self.assertEqual(state['elapsed_seconds'],60)
        self.assertEqual(self.restart(),state)
    def test_pending_latest_does_not_display_previous_consumption(self):
        self.event(0);self.consume();self.event(1);self.consume();self.event(2,pending=True)
        self.assertEqual(self.worker.status()['state'],'pending');self.assertIsNone(self.worker.status()['value']);self.assertFalse(self.worker.once())
    def test_clock_reset_utc_jump_missing_metadata_and_camera_change_are_segments(self):
        self.event(0);before=self.consume()
        self.event(1,tick=1000000,boot='boot-b');state=self.consume()
        self.assertEqual(state['state'],'anchored');self.assertNotEqual(state['segment_id'],before['segment_id']);self.assertEqual(state['gap_reason'],'capture_clock_changed')
        self.event(2,boot='boot-b',utc_jump=2);state=self.consume();self.assertEqual(state['gap_reason'],'capture_clock_utc_discontinuity');self.assertEqual(state['state'],'anchored')
        self.event(3,boot='boot-b',clock=False);state=self.consume();self.assertEqual(state['reason'],'capture_clock_missing');self.assertIsNone(state['value'])
        self.event(4,boot='boot-b');state=self.consume();self.assertEqual(state['state'],'anchored')
        self.event(5,boot='boot-b',camera='other');state=self.consume();self.assertEqual(state['gap_reason'],'capture_camera_changed')
        self.assertEqual(self.restart(),state)
    def test_changed_format_creates_new_relative_segment_and_preserves_old_rows(self):
        self.event(0);self.consume();self.event(1);before=self.consume()
        revised=document();revised['unit']='m3';self.formats.save(revised,self.saved['revision']);state=self.consume()
        self.assertEqual(state['state'],'anchored');self.assertEqual(state['unit'],'m3');self.assertNotEqual(state['segment_id'],before['segment_id'])
        with self.store.connect() as db:
            saved=json.loads(db.execute('SELECT result FROM consumption_records WHERE segment_id=? ORDER BY event_id DESC LIMIT 1',(before['segment_id'],)).fetchone()[0])
        self.assertEqual(saved,before)
    def test_engine_upgrade_preserves_old_decisions_and_starts_new_relative_anchor(self):
        self.event(0);self.consume();self.event(1);before=self.consume()
        self.worker._drop();self.worker=Consumption(self.store,self.recognition,self.formats,LIBRARY)
        self.worker.engine='b'*64  # Simulated accounting software upgrade.
        after=self.consume();self.assertEqual(after['state'],'anchored');self.assertEqual(after['value'],0)
        self.assertNotEqual(after['segment_id'],before['segment_id'])
        self.assertEqual(after['gap_reason'],'interpretation_changed')
        with self.store.connect() as db:
            saved=json.loads(db.execute('SELECT result FROM consumption_records WHERE segment_id=? ORDER BY event_id DESC LIMIT 1',(before['segment_id'],)).fetchone()[0])
        self.assertEqual(saved,before)
    def test_interpretation_or_pipeline_change_immediately_hides_previous_quantity(self):
        self.event(0);self.consume();self.event(1);before=self.consume()
        self.assertEqual(before['value'],1)
        revised=document();revised['unit']='m3'
        self.formats.save(revised,self.saved['revision'])
        self.assertEqual(self.worker.status()['state'],'recovering');self.assertIsNone(self.worker.status()['value'])
        self.consume();self.reader.pipeline_id='b'*64
        self.assertEqual(self.worker.status()['state'],'unavailable');self.assertIsNone(self.worker.status()['value'])
        self.reader.pipeline_id=PIPELINE;self.formats.active=None
        self.assertEqual(self.worker.status()['state'],'not_configured');self.assertIsNone(self.worker.status()['value'])
    def test_backward_converted_quantity_is_rejected_under_bound(self):
        revised=document(errors=(0,0),rate=.1);self.formats.save(revised,self.saved['revision'])
        self.event(12);self.consume();self.event(11);state=self.consume()
        self.assertEqual(state['state'],'unavailable');self.assertEqual(state['reason'],'consumption_positions_contradict_bounds');self.assertIsNone(state['value'])
    def test_corrupt_saved_result_preserved_and_recovery_blocks(self):
        self.event(0);state=self.consume()
        with self.store.connect() as db:db.execute('UPDATE consumption_records SET result=?',(b'broken',))
        self.worker._drop();self.worker=Consumption(self.store,self.recognition,self.formats,LIBRARY)
        with self.assertRaises(ValueError):self.worker.once()
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT result FROM consumption_records').fetchone()[0],b'broken')
    def test_inference_provenance_cannot_become_verified_accuracy(self):
        digest=self.event(0)
        with self.store.connect() as db:
            row=json.loads(db.execute('SELECT result FROM inference').fetchone()[0]);row['accuracy_verified']=True
            db.execute('UPDATE inference SET result=?',(json.dumps(row),))
        state=self.consume();self.assertEqual(state['state'],'unavailable');self.assertFalse(state['accuracy_verified']);self.assertFalse(state['training_allowed'])
    def test_failed_record_write_then_restart_recovers_original_turn_path(self):
        self.event(0);self.consume();self.event(1)
        original=self.store.connect
        class Broken:
            def __init__(self,db):self.db=db
            def execute(self,sql,*args):
                if sql.startswith('INSERT INTO consumption_records'):raise sqlite3.OperationalError('disk full')
                return self.db.execute(sql,*args)
        @contextmanager
        def fail():
            with original() as db:yield Broken(db)
        with patch.object(self.store,'connect',fail),self.assertRaises(sqlite3.OperationalError):self.worker.once()
        # A process restart drops uncommitted native state and replays durable events.
        state=self.restart();self.assertAlmostEqual(state['value'],1)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM consumption_records').fetchone()[0],2)
    def test_uncertain_post_commit_interruption_recovers_without_double_counting(self):
        self.event(0);self.consume();self.event(1)
        original=self.store.connect;written=[False]
        class Watch:
            def __init__(self,db):self.db=db
            def execute(self,sql,*args):
                if sql.startswith('INSERT INTO consumption_records'):written[0]=True
                return self.db.execute(sql,*args)
        @contextmanager
        def interrupted():
            with original() as db:yield Watch(db)
            if written[0]:raise OSError('simulated process interruption after commit')
        with patch.object(self.store,'connect',interrupted),self.assertRaises(OSError):self.worker.once()
        state=self.restart();self.assertAlmostEqual(state['value'],1)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM consumption_records').fetchone()[0],2)
    def test_two_workers_share_one_durable_decision_per_capture(self):
        other=Consumption(self.store,self.recognition,self.formats,LIBRARY)
        try:
            self.event(0);first=self.consume();self.assertTrue(other.once());self.assertEqual(other.status(),first)
            for quantity in range(1,5):
                self.event(quantity);first=self.consume();self.assertTrue(other.once());self.assertEqual(other.status(),first)
            with self.store.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM consumption_segments').fetchone()[0],1)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM consumption_records').fetchone()[0],5)
            self.event(5,boot='new',tick=1000000);first=self.consume()
            self.assertEqual(other.status()['state'],'recovering');self.assertTrue(other.once());self.assertEqual(other.status(),first)
        finally:other._drop()
    def test_invalid_native_inputs_are_bounded(self):
        native=AccountingNative(LIBRARY);tracker=native.tracker(document())
        try:
            for positions,tick,clock in (([0],1,'boot'),([True,0],1,'boot'),([10**400,0],1,'boot'),([0,0],-1,'boot'),([0,0],1,'\u03b1')):
                with self.assertRaises(ValueError):tracker.observe(positions,tick,clock)
            tracker.close()
            with self.assertRaisesRegex(ValueError,'tracker_closed'):tracker.observe([0,0],1,'boot')
        finally:tracker.close()

if __name__=='__main__':unittest.main()
