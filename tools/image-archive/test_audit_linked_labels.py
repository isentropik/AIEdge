import copy,unittest
from audit_linked_labels import audit

def fixture(h,l):
 return dict(version=1,method='independent_reading',training_eligible=False,position_scale='0_to_10_in_each_dials_numbering',dials=['high','low'],images=[dict(image_sha256='a'*64,training_eligible=False,readings={'high':h,'low':l})])
class LinkedTests(unittest.TestCase):
 def pair(self,h,l,error=.1):return audit(fixture(h,l),['high','low'],error)['rows'][0]['pairs'][0]
 def test_observed_disagreement_is_flagged(self):
  p=self.pair(5.34,4.78);self.assertEqual(p['status'],'review');self.assertAlmostEqual(p['signed_residual'],-.138);self.assertAlmostEqual(p['linked_position'],5.478)
 def test_rollover_both_directions(self):
  for h,l in [(9.99,0.1),(.01,9.9)]:self.assertEqual(self.pair(h,l)['status'],'consistent_with_assumption')
 def test_unknown_and_no_mutation(self):
  d=fixture(None,4.8);before=copy.deepcopy(d);r=audit(d,['high','low'],.1)
  self.assertEqual(d,before);self.assertEqual(r['rows'][0]['pairs'][0]['status'],'unknown');self.assertFalse(r['training_eligible'])
 def test_approximate_labels_depend_on_explicit_assumption(self):
  self.assertEqual(self.pair(5.2,3.05)['status'],'consistent_with_assumption');self.assertEqual(self.pair(5.2,3.05,.05)['status'],'review')
 def test_invalid_values_and_sequence(self):
  for v in [True,-1,10,float('nan'),'5']:
   with self.assertRaises(ValueError):self.pair(v,3)
  for seq in [['high'],['high','high'],['high','missing']]:
   with self.assertRaises(ValueError):audit(fixture(5.3,3),seq,.1)
  for e in [True,-1,.5,float('nan')]:
   with self.assertRaises(ValueError):audit(fixture(5.3,3),['high','low'],e)
 def test_duplicate_images_rejected(self):
  d=fixture(5.3,3);d['images']*=2
  with self.assertRaises(ValueError):audit(d,['high','low'],.1)
if __name__=='__main__':unittest.main()
