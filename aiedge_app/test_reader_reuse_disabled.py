import unittest
from test_reader_observation_mask import reader,FakePrepared
class Runtime(FakePrepared):
 def __init__(self):super().__init__();self.full=0;self.masked=0;self.reuse=0
 def prepare(self,rgb,sparse=False):self.full+=1;return super().prepare(rgb,sparse)
 def prepare_with_reuse(self,rgb,sparse=False):self.reuse+=1;return super().prepare(rgb,sparse)
 def prepare_masked(self,rgb,observed,sparse=False):
  self.masked+=1;rows=super().prepare(rgb,sparse)
  for i,f in enumerate(observed):
   if not f:rows[i]={'state':'unavailable','visibility':None,'features':None,'reused':False}
  return rows
class Tests(unittest.TestCase):
 def test_disabled_repeat_no_native_or_model_reuse(self):
  r=reader(False);r.runtime=Runtime();mask=[False]*4+[True]*2
  for _ in range(2):
   x=r.read_rgb(b'synthetic',observed=mask);self.assertEqual(x['state'],'estimated');self.assertEqual(x['work']['preprocessing_reused'],0);self.assertEqual(x['work']['inference_reused'],0);self.assertEqual(r.last_dials,{})
  self.assertEqual((r.runtime.full,r.runtime.masked,r.runtime.reuse),(2,0,0));self.assertEqual(r.networks['main'][0].calls,2);self.assertEqual(r.networks['secondary'][0].calls,2)
 def test_enabled_masked_then_full_cache(self):
  r=reader(True);r.runtime=Runtime();r.read_rgb(b'synthetic');r.read_rgb(b'synthetic',observed=[False]*4+[True]*2);self.assertEqual(set(r.last_dials),{4,5});x=r.read_rgb(b'synthetic');self.assertEqual((r.runtime.masked,r.runtime.reuse,r.runtime.full),(1,2,0));self.assertEqual(r.networks['main'][0].calls,9);self.assertEqual(x['work']['inference_reused'],2)
 def test_disabled_partial_then_full_invokes_all(self):
  r=reader(False);r.runtime=Runtime();r.read_rgb(b'synthetic',observed=[False]*4+[True]*2);r.read_rgb(b'synthetic');self.assertEqual(r.runtime.full,2);self.assertEqual(r.runtime.masked,0);self.assertEqual(r.networks['main'][0].calls,6);self.assertEqual(r.networks['secondary'][0].calls,2)
if __name__=='__main__':unittest.main()
