"""Injected preparation and fake tensors only; never creates/loads real models."""
import sys,types,threading,copy,hashlib,io,unittest
import numpy as np
from PIL import Image
# Reader imports LiteRT but injected tests do not construct an interpreter.
try:import ai_edge_litert.interpreter
except ModuleNotFoundError:
    package=types.ModuleType('ai_edge_litert');interp=types.ModuleType('ai_edge_litert.interpreter')
    interp.Interpreter=object;interp.OpResolverType=types.SimpleNamespace(BUILTIN_REF=0)
    sys.modules['ai_edge_litert']=package;sys.modules['ai_edge_litert.interpreter']=interp
from reader import Reader

class FakeNetwork:
    def __init__(self,role):self.role=role;self.calls=0;self.inputs=[];self.fail=False
    def set_tensor(self,index,value):self.inputs.append(value.copy())
    def invoke(self):
        self.calls+=1
        if self.fail:raise RuntimeError('synthetic network failure')
    def get_tensor(self,index):
        return np.full((1,360),1/360,dtype=np.float32) if self.role=='main' else np.zeros((1,360),dtype=np.int8)
class FakePrepared:
    def __init__(self):
        self.calls=0;self.fail=False;self.decoded=0
        self.rows=[{'state':'ok','visibility':1,'features':bytes([i])*15360} for i in range(6)]
    def prepare(self,rgb,sparse=False):
        self.calls+=1
        if self.fail:raise ValueError('synthetic alignment rejection')
        return copy.deepcopy(self.rows)
    def prepare_with_reuse(self,rgb,sparse=False):return self.prepare(rgb,sparse)
    def decode(self,scores,ccw):self.decoded+=1;return .25 if ccw else 2.5
def reader(reuse=True):
    r=Reader.__new__(Reader);r.lock=threading.Lock();r.sampling_sparse=False;r.native=FakePrepared();r.runtime=None;r.reuse_unchanged=reuse;r.last_dials={};r.profile='synthetic-only';r.hashes={'main':'a'*64,'secondary':'b'*64};r.pipeline_ids={False:'c'*64,True:'d'*64};r.pipeline_id='c'*64
    r.dials=[{'name':str(i),'model':'secondary' if i==5 else 'main','direction':'ccw' if i%2==0 else 'cw'} for i in range(6)]
    r.networks={role:(FakeNetwork(role),{'index':0},{'index':1}) for role in ['main','secondary']};return r
def jpeg():
    out=io.BytesIO();Image.new('RGB',(640,480),(20,40,60)).save(out,'JPEG');return out.getvalue()

class ObservationMaskReaderTests(unittest.TestCase):
    def test_default_full_parity_and_no_additive_mask_fields(self):
        a,b=reader(),reader();x=a.read_rgb(b'synthetic');y=b.read_rgb(b'synthetic',observed=None)
        x.pop('processing_seconds');y.pop('processing_seconds');self.assertEqual(x,y);self.assertNotIn('_observed_mask',x);self.assertEqual(a.networks['main'][0].calls,5);self.assertEqual(a.networks['secondary'][0].calls,1)
    def test_only_selected_network_calls_and_no_omitted_output_cache(self):
        r=reader();mask=[False]*4+[True,True];x=r.read_rgb(b'synthetic',observed=mask)
        self.assertEqual(x['state'],'estimated');self.assertEqual(r.native.calls,1);self.assertEqual(r.networks['main'][0].calls,1);self.assertEqual(r.networks['secondary'][0].calls,1);self.assertEqual(set(r.last_dials),{4,5})
        for row in x['dial_positions'][:4]:self.assertEqual(row['state'],'unavailable');self.assertIsNone(row['position']);self.assertNotIn('scores_sha256',row)
    def test_full_partial_full_reinvokes_omitted_dials(self):
        r=reader();r.read_rgb(b'synthetic');self.assertEqual(r.networks['main'][0].calls,5)
        r.read_rgb(b'synthetic',observed=[False]*4+[True,True]);self.assertEqual(set(r.last_dials),{4,5});self.assertEqual(r.networks['main'][0].calls,5)
        x=r.read_rgb(b'synthetic');self.assertEqual(r.networks['main'][0].calls,9);self.assertEqual(r.networks['secondary'][0].calls,1);self.assertEqual(x['work']['inference_reused'],2);self.assertEqual(r.native.calls,3)
    def test_malformed_masks_fail_before_preparation_network_or_jpeg_decode(self):
        for mask in [[],[True]*5,[False]*6,[1]*6,'bad',[True]*7,[None]*6]:
            r=reader()
            with self.subTest(mask=mask),self.assertRaisesRegex(ValueError,'invalid_reader_observation_mask'):r.read_rgb(b'bad',observed=mask)
            with self.assertRaisesRegex(ValueError,'invalid_reader_observation_mask'):r.read_jpeg(b'notJPEG',observed=mask)
            self.assertEqual(r.native.calls,0);self.assertEqual(r.networks['main'][0].calls,0)
    def test_selected_preparation_rejection_is_overall_rejected(self):
        r=reader();r.native.rows[4]['state']='occluded';x=r.read_jpeg(jpeg(),observed=[False]*4+[True,True]);self.assertEqual(x['state'],'rejected');self.assertNotIn('observation_support',x);self.assertEqual(x['observation_attempt']['requested_observed'],[False]*4+[True,True]);self.assertEqual(r.networks['main'][0].calls,0)
    def test_omitted_preparation_failures_not_observed(self):
        r=reader()
        for row in r.native.rows[:4]:row.update(state='occluded',features=None)
        x=r.read_rgb(b'synthetic',observed=[False]*4+[True,True]);self.assertEqual(x['state'],'estimated');self.assertEqual(r.networks['main'][0].calls,1)
        self.assertTrue(all(row['state']=='unavailable' and row['position'] is None for row in x['dial_positions'][:4]))
    def test_jpeg_support_exact_hash_pipeline_and_private_mask_removed(self):
        r=reader();blob=jpeg();mask=[False]*4+[True,True];x=r.read_jpeg(blob,observed=tuple(mask));self.assertNotIn('_observed_mask',x)
        self.assertEqual(x['observation_support'],{'schema_version':1,'source_sha256':hashlib.sha256(blob).hexdigest(),'pipeline_id':r.pipeline_id,'observed':mask})
        mask[0]=True;self.assertFalse(x['observation_support']['observed'][0])
    def test_alignment_failure_clears_all_cache_and_binds_only_attempt(self):
        r=reader();r.read_rgb(b'synthetic');r.native.fail=True;blob=jpeg();x=r.read_jpeg(blob,observed=[False]*4+[True,True]);self.assertEqual(x['state'],'rejected');self.assertEqual(r.last_dials,{});self.assertNotIn('observation_support',x);self.assertEqual(x['observation_attempt']['source_sha256'],hashlib.sha256(blob).hexdigest())
    def test_selected_network_failure_returns_rejected_attempt_no_stale_outputs(self):
        r=reader();r.networks['main'][0].fail=True;x=r.read_jpeg(jpeg(),observed=[False]*4+[True,True]);self.assertEqual(x['state'],'rejected');self.assertEqual(x['dial_positions'],[]);self.assertEqual(r.last_dials,{});self.assertIn('observation_attempt',x)
    def test_default_network_failure_keeps_legacy_exception(self):
        r=reader();r.networks['main'][0].fail=True
        with self.assertRaises(RuntimeError):r.read_rgb(b'synthetic')
        self.assertEqual(r.last_dials,{})
    def test_explicit_all_true_matches_full_rows(self):
        a,b=reader(),reader();x=a.read_rgb(b'synthetic');y=b.read_rgb(b'synthetic',observed=[True]*6);self.assertEqual(x['dial_positions'],y['dial_positions']);self.assertEqual(x['state'],y['state'])

if __name__=='__main__':unittest.main()
