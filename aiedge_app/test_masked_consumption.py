"""Actual native/SQLite integration with invented phases only, no images/models."""
import copy,hashlib,json,os,tempfile,unittest
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from capture import Store,now
from recognition import Recognition,decode_result
from reading_format import FormatStore
from consumption import Consumption
from observation_support import document_observation

PIPELINE='a'*64;LIBRARY=os.environ.get('AIEDGE_ACCOUNTING_LIBRARY')
def result(digest,values,mask=None):
    r={'state':'estimated','pipeline_id':PIPELINE,'source_sha256':digest,'training_allowed':False,'accuracy_verified':False,
       'dial_positions':[{'state':'estimated','position':v} for v in values]}
    if mask is not None:
        r['observation_support']={'schema_version':1,'source_sha256':digest,'pipeline_id':PIPELINE,'observed':mask}
        for row,flag in zip(r['dial_positions'],mask):
            if flag is False:row.update(state='unavailable',position=None)
    return r

class SupportTests(unittest.TestCase):
    def test_legacy_full_and_mask_permutation(self):
        r=result('b'*64,[1,2,3]);self.assertEqual(document_observation(r,[1,0,2]),([2,1,3],[True]*3))
        r=result('b'*64,[1,2,3],[True,False,True]);self.assertEqual(document_observation(r,[1,0,2]),([None,1,3],[False,True,True]))
    def test_mask_provenance_and_stale_rows_rejected(self):
        base=result('b'*64,[1,2,3],[False,True,True])
        mutations=[lambda r:r.update(observation_support=None),lambda r:r['dial_positions'][1].update(position=10**400),lambda r:r['observation_support']['observed'].__setitem__(0,0),lambda r:r['observation_support'].update(source_sha256='c'*64),lambda r:r['observation_support'].update(schema_version=True),lambda r:r['dial_positions'][0].update(position=1),lambda r:r['dial_positions'][0].update(state='estimated'),lambda r:r['dial_positions'][1].update(source_sha256='c'*64)]
        for mutate in mutations:
            r=copy.deepcopy(base);mutate(r)
            with self.subTest(r=r),self.assertRaises(ValueError):decode_result(json.dumps(r),'b'*64,PIPELINE)

@unittest.skipUnless(LIBRARY,'actual accounting library required')
class MaskedConsumptionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);self.reader=SimpleNamespace(pipeline_id=PIPELINE,dials=[{'name':str(i)} for i in range(3)])
        self.recognition=Recognition(self.store,self.reader);self.formats=FormatStore(self.temp.name,self.recognition)
        self.doc={'version':1,'pipeline_id':PIPELINE,'unit':'ft3','maximum_rate_per_second':50,'dials':[{'index':i,'value_per_revolution':p,'position_error':.01} for i,p in enumerate([10000,1000,5])]}
        self.saved=self.formats.save(self.doc,None);self.worker=Consumption(self.store,self.recognition,self.formats,LIBRARY);self.counter=0;self.tick=1000000
    def tearDown(self):self.worker._drop();self.temp.cleanup()
    def event(self,value,mask=None,tick=None,clock='boot-a',duplicate=False,mutate=None):
        self.counter+=1;tick=self.tick if tick is None else tick;self.tick=tick+1000000
        data=b'\xff\xd8'+(b'repeat' if duplicate else str(self.counter).encode())+b'\xff\xd9';digest=hashlib.sha256(data).hexdigest()
        stamp=(datetime(2026,10,4,tzinfo=timezone.utc)+timedelta(microseconds=tick)).isoformat()
        headers={'X-AIEdge-Frame-Id':str(self.counter),'X-AIEdge-Captured-At':stamp,'X-AIEdge-SHA256':digest,'X-AIEdge-Clock-Id':clock,'X-AIEdge-Capture-Monotonic-Us':str(tick)}
        self.store.add('fixture',data,headers)
        phases=[value%p/p*10 for p in [10000,1000,5]];r=result(digest,phases,mask)
        if mutate:mutate(r)
        with self.store.connect() as db:db.execute('INSERT OR IGNORE INTO inference VALUES(?,?,?,?)',(digest,PIPELINE,now(),json.dumps(r)))
        self.assertTrue(self.worker.once());return self.worker.status()
    def restart(self):
        self.worker._drop();self.worker=Consumption(self.store,self.recognition,self.formats,LIBRARY)
        while self.worker.once():pass
        return self.worker.status()
    def records(self):
        with self.store.connect() as db:return list(db.execute('SELECT segment_id,event_id,result FROM consumption_records ORDER BY segment_id,event_id'))
    def test_full_partial_full_relative_and_absolute_replay(self):
        self.assertEqual(self.event(998.3)['state'],'anchored')
        p=self.event(1003.3,[False,True,True]);self.assertAlmostEqual(p['value'],5);self.assertEqual(p['absolute']['state'],'unavailable');self.assertIsNone(p['absolute']['value']);self.assertEqual(p['observation_support']['document_observed'],[False,True,True])
        full=self.event(1010.3);self.assertAlmostEqual(full['value'],12);self.assertNotEqual(full['absolute'].get('reason'),'partial_observation_no_absolute_reading');self.assertEqual(self.restart(),full);self.assertEqual(len(self.records()),3)
    def test_partial_bootstrap_and_missing_finest(self):
        p=self.event(1,[False,True,True]);self.assertEqual(p['reason'],'consumption_partial_requires_full_anchor');self.assertIsNone(self.worker.anchor);self.assertEqual(p['observation_support']['document_observed'],[False,True,True])
        full=self.event(2);self.assertEqual(full['state'],'anchored')
        p=self.event(3,[True,True,False]);self.assertEqual(p['reason'],'consumption_finest_dial_missing');self.assertIsNone(p['value']);self.assertEqual(p['observation_support']['document_observed'],[True,True,False])
    def test_stale_upper_and_invalid_mask_are_durable_rejections(self):
        self.event(0)
        for change in [lambda r:r['dial_positions'][0].update(position=0),lambda r:r['observation_support']['observed'].__setitem__(0,0)]:
            p=self.event(1,[False,True,True],mutate=change);self.assertEqual(p['state'],'unavailable');self.assertIsNone(p['value'])
        self.assertEqual(len(self.records()),3);self.assertEqual(self.restart(),p)
    def test_unbounded_alias_retains_no_scalar(self):
        doc=copy.deepcopy(self.doc);doc.pop('maximum_rate_per_second');self.formats.save(doc,self.saved['revision'])
        self.event(0);p=self.event(1000,[False,True,True]);self.assertEqual(p['state'],'ambiguous');self.assertTrue(p['upper_unbounded']);self.assertIsNone(p['maximum']);self.assertIsNone(p['value']);self.assertIsNone(p['absolute']['value']);self.assertEqual(self.restart(),p)
    def test_same_jpeg_keeps_every_clock_event(self):
        self.event(10,duplicate=True)
        a=self.event(10,duplicate=True);b=self.event(10,duplicate=True);self.assertNotEqual(a['event_id'],b['event_id']);self.assertEqual(len(self.records()),3);self.assertEqual(self.store.status()['unique_images'],1);self.assertIsNone(b['value']);self.assertEqual(self.restart(),b)
    def test_clock_reset_links_old_segment_without_inventing_delta(self):
        old=self.event(0);self.event(1);before=self.records()
        p=self.event(2,[False,True,True],tick=1000000,clock='boot-b');self.assertNotEqual(p['segment_id'],old['segment_id']);self.assertEqual(p['prior_segment_id'],old['segment_id']);self.assertIsNone(p['unresolved_gap']['delta']);self.assertEqual(p['reason'],'consumption_partial_requires_full_anchor')
        full=self.event(3,clock='boot-b');self.assertEqual(full['state'],'anchored');self.assertEqual(full['prior_segment_id'],old['segment_id']);self.assertEqual(self.restart(),full)
        for row in before:self.assertIn(row,self.records())
    def test_engine_migration_preserves_old_decisions(self):
        self.event(0);old=self.event(1);before=self.records();self.worker.engine='synthetic-other-engine'
        migrated=self.event(2,[False,True,True]);self.assertNotEqual(migrated['segment_id'],old['segment_id']);self.assertEqual(migrated['prior_segment_id'],old['segment_id']);self.assertEqual(migrated['reason'],'consumption_partial_requires_full_anchor')
        for row in before:self.assertIn(row,self.records())
    def test_partial_capability_floor(self):
        self.event(0);self.worker.native.supports_masked=False;p=self.event(1,[False,True,True]);self.assertEqual(p['reason'],'consumption_mask_unsupported');self.assertIsNone(p['value'])
    def test_reader_order_maps_explicit_mask_to_document_order(self):
        doc=copy.deepcopy(self.doc);doc['dials'][0]['index']=1;doc['dials'][1]['index']=0;self.formats.save(doc,self.saved['revision'])
        def swap(r):
            r['dial_positions'][0],r['dial_positions'][1]=r['dial_positions'][1],r['dial_positions'][0]
            if 'observation_support' in r:
                flags=r['observation_support']['observed'];flags[0],flags[1]=flags[1],flags[0]
        self.event(998.3,mutate=swap);p=self.event(1003.3,[False,True,True],mutate=swap)
        self.assertAlmostEqual(p['value'],5);self.assertEqual(p['observation_support']['reader_observed'],[True,False,True]);self.assertEqual(p['observation_support']['document_observed'],[False,True,True]);self.assertEqual(self.restart(),p)
    def test_second_worker_replays_identical_segment_links_and_decisions(self):
        self.event(0);self.event(1);self.event(2,[False,True,True],tick=1000000,clock='boot-b');state=self.event(3,clock='boot-b');before=self.records()
        other=Consumption(self.store,self.recognition,self.formats,LIBRARY)
        try:
            while other.once():pass
            self.assertEqual(other.status(),state);self.assertEqual(self.records(),before)
        finally:other._drop()
    def test_explicit_null_support_and_huge_known_value_rejected_without_crash(self):
        self.event(0)
        for mutate in [lambda r:r.update(observation_support=None),lambda r:r['dial_positions'][1].update(position=10**400)]:
            p=self.event(1,[False,True,True],mutate=mutate);self.assertEqual(p['state'],'unavailable');self.assertIsNone(p['value'])
        self.assertEqual(self.restart(),p)
    def test_saved_segment_links_validate_before_replay(self):
        first=self.event(0);second=self.event(1,tick=1000000,clock='boot-b');segment=second['segment_id'];self.worker._drop()
        for assignment in ["unresolved_gap_reason='interpretation_changed'","first_event=999","prior_segment_id=segment_id"]:
            with self.store.connect() as db:
                db.execute('UPDATE consumption_segment_links SET prior_segment_id=?,unresolved_gap_reason=?,first_event=? WHERE segment_id=?',(first['segment_id'],second['gap_reason'],second['event_id'],segment))
                db.execute('UPDATE consumption_segment_links SET '+assignment+' WHERE segment_id=?',(segment,))
            self.worker=Consumption(self.store,self.recognition,self.formats,LIBRARY)
            with self.assertRaisesRegex(ValueError,'segment_link_invalid'):self.worker.once()
            self.worker._drop()

if __name__=='__main__':unittest.main()
