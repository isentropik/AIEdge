"""Synthetic release migration, ABI and deterministic restart checks."""
import copy,hashlib,json,os,unittest
from pathlib import Path
from unittest.mock import patch
from accounting_native import AccountingNative
import test_event_consumption as fixtures
LIBRARY,READING=fixtures.LIBRARY,fixtures.READING
from event_recognition import EventRecognition
from reading_format import FormatStore
from consumption import Consumption

@unittest.skipUnless(LIBRARY and READING,'host native libraries required')
class AccountingMigrationTests(unittest.TestCase):
    setUp=fixtures.EventConsumptionTests.setUp
    tearDown=fixtures.EventConsumptionTests.tearDown
    event=fixtures.EventConsumptionTests.event
    consume=fixtures.EventConsumptionTests.consume
    recognize_consume=fixtures.EventConsumptionTests.recognize_consume
    records=fixtures.EventConsumptionTests.records
    restart_consumption=fixtures.EventConsumptionTests.restart_consumption
    def snapshot(self):
        tables=['capture_events','event_recognition_requests','event_recognition_cache',
                'event_recognition_bindings','consumption_segments','consumption_records','consumption_segment_links']
        with self.store.connect() as db:return {t:list(db.execute('SELECT * FROM '+t+' ORDER BY rowid')) for t in tables}
    def old_context(self):
        # setUp constructs an unused new-context fixture; remove only that
        # synthetic empty row so this test begins with an old-only database.
        with self.store.connect() as db:
            db.execute('DELETE FROM event_selection_contexts WHERE context=?',(self.recognition.observation_context,))
        # Simulate the old wrapper source fingerprint, without copying private
        # source/data or changing any file. All other context inputs stay fixed.
        original=Path.read_bytes
        def old_bytes(path):
            return b'synthetic previous accounting wrapper' if path.name=='accounting_native.py' else original(path)
        with patch.object(Path,'read_bytes',old_bytes):
            self.recognition=EventRecognition(self.store,self.reader,self.document,self.config,self.capabilities)
        self.worker._drop();self.formats=FormatStore(self.temp.name,self.recognition)
        self.worker=Consumption(self.store,self.recognition,self.formats,LIBRARY)
    def test_source_upgrade_is_future_only_and_preserves_history(self):
        self.old_context();old=self.recognize_consume(100);self.recognize_consume(100.1)
        old_context=self.recognition.observation_context;before=self.snapshot();calls=list(self.reader.calls)
        self.worker._drop()
        current=EventRecognition(self.store,self.reader,self.document,self.config,self.capabilities)
        self.assertNotEqual(current.observation_context,old_context);self.assertEqual(current.observation_first_event,3)
        self.recognition=current;self.formats=FormatStore(self.temp.name,current)
        self.worker=Consumption(self.store,current,self.formats,LIBRARY)
        self.assertFalse(current.once());self.assertFalse(self.worker.once());self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.reader.calls,calls)
        # Restart while the new context is still waiting must keep its floor.
        again=EventRecognition(self.store,self.reader,self.document,self.config,self.capabilities)
        self.assertEqual(again.observation_context,current.observation_context);self.assertEqual(again.observation_first_event,3)
        new=self.recognize_consume(100.2)
        self.assertEqual(new['event_id'],3);self.assertEqual(new['state'],'anchored')
        self.assertEqual(new['prior_segment_id'],old['segment_id'])
        self.assertEqual(new['unresolved_gap']['reason'],'interpretation_changed');self.assertIsNone(new['unresolved_gap']['delta'])
        after=self.snapshot()
        for table,rows in before.items():
            for row in rows:self.assertIn(row,after[table])
        self.assertEqual(self.restart_consumption(),new)
    def test_ambiguous_candidates_survive_restart_without_inference_or_record_changes(self):
        self.worker._drop()
        for dial in self.document['dials']:dial['position_error']=.1
        self.recognition=EventRecognition(self.store,self.reader,self.document,self.config,self.capabilities)
        self.formats=FormatStore(self.temp.name,self.recognition)
        self.formats.save(self.document,self.saved['revision'])
        self.worker=Consumption(self.store,self.recognition,self.formats,LIBRARY)
        self.recognize_consume(100,tick=1000000)
        state=self.recognize_consume(100,tick=13000000)
        self.assertEqual(state['state'],'ambiguous')
        for tick in (19000000,25000000,31000000):state=self.recognize_consume(100,tick=tick)
        before=self.snapshot();calls=list(self.reader.calls)
        self.assertEqual(self.restart_consumption(),state);self.assertEqual(self.snapshot(),before);self.assertEqual(self.reader.calls,calls)
        later=self.recognize_consume(100,tick=37000000)
        self.assertEqual(later['state'],'ambiguous');self.assertIsNone(later['value'])
        self.assertLessEqual(later['maximum'],5.101)
    def test_old_native_package_is_rejected(self):
        class Function:
            def __call__(self):return 1
        class Legacy:
            aiedge_accounting_abi=Function()
        with patch('accounting_native.ctypes.CDLL',return_value=Legacy()):
            with self.assertRaisesRegex(ValueError,'accounting_branch_abi_required'):AccountingNative(LIBRARY)
    def test_wrong_branch_capability_is_rejected(self):
        class Function:
            def __init__(self,value):self.value=value
            def __call__(self):return self.value
        class Wrong:
            aiedge_accounting_abi=Function(1)
            aiedge_accounting_branch_abi=Function(2)
        with patch('accounting_native.ctypes.CDLL',return_value=Wrong()):
            with self.assertRaisesRegex(ValueError,'unsupported_accounting_branch_abi'):AccountingNative(LIBRARY)

if __name__=='__main__':unittest.main()
