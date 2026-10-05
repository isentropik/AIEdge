import unittest
from test_reader_observation_mask import reader,FakePrepared
class Runtime(FakePrepared):
 def prepare_masked(self,rgb,observed,sparse=False):
  self.mask=list(observed);rows=self.prepare(rgb,sparse)
  for i,f in enumerate(observed):
   if not f:rows[i]={'state':'unavailable','visibility':None,'features':None,'reused':False}
  return rows
class Tests(unittest.TestCase):
 def test_masked_runtime_routed(self):
  r=reader();r.runtime=Runtime();x=r.read_rgb(b'synthetic',observed=[False]*4+[True]*2);self.assertEqual(r.runtime.mask,[False]*4+[True]*2);self.assertEqual(x['state'],'estimated');self.assertEqual(r.networks['main'][0].calls,1)
 def test_legacy_injected_runtime_fallback(self):
  r=reader();r.runtime=FakePrepared();self.assertEqual(r.read_rgb(b'synthetic',observed=[False]*4+[True]*2)['state'],'estimated')
 def test_explicit_unsupported_native_rejected(self):
  class Old(Runtime):
   def prepare_masked(self,*a,**kw):raise ValueError('masked_preparation_unsupported')
  r=reader();r.runtime=Old();x=r.read_rgb(b'synthetic',observed=[False]*4+[True]*2);self.assertEqual(x['state'],'rejected');self.assertEqual(r.networks['main'][0].calls,0)
if __name__=='__main__':unittest.main()
