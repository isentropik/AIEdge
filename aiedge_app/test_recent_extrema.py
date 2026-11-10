import copy,random,unittest
from decimal import Decimal as D
from unittest.mock import patch
from daily_constraints import Budget,WorkLimit
from daily_empirical import comparisons
from recent_usage import recent_comparisons,MAX_COMPARISON_ANCHORS

class RecentExtremaTests(unittest.TestCase):
 def rows(self,times):
  return [dict(event_id=i+1,event_observation=dict(event_id=i+1,camera='saved',clock_id='boot',context_id='c',format_id='f',monotonic_us=t*1000000),delta=None,unresolved_gap={'reason':'timeout','delta':None}) for i,t in enumerate(times)]
 def solve(self,rows,values):return recent_comparisons(rows,list(map(D,values)),D(6),Budget())
 def test_unsampled_extrema_pair_is_added(self):
  rows=self.rows([0,10,20,130,140]);v=list(map(D,['10','14','11','11','9']))
  before=copy.deepcopy(rows);old=comparisons(rows,v,D(6),Budget());new=self.solve(rows,v)
  self.assertNotIn((2,5,D(0),D(1)),old)
  self.assertIn((2,5,D(0),D(1)),new);self.assertEqual(rows,before)
 def test_original_constraints_are_retained(self):
  r=self.rows(range(0,3601,10));v=[D(i)/100 for i in range(len(r))]
  old=comparisons(r,v,D(6),Budget());self.assertEqual(self.solve(r,v)[:len(old)],old)
 def test_no_comparison_crosses_identity(self):
  for key in ('camera','clock_id','context_id','format_id'):
   r=self.rows([0,10,130,140]);r[2]['event_observation'][key]='different';r[3]['event_observation'][key]='different'
   edges=self.solve(r,[10,12,8,10])
   self.assertTrue(all((a<=2)==(b<=2) for a,b,lo,hi in edges))
 def test_time_and_geometry_scope_not_extended(self):
  r=self.rows([0,10,3601,3610]);v=[D(0),D(30),D(10),D(50)]
  for a,b,lo,hi in self.solve(r,v):
   self.assertLessEqual(r[b-1]['event_observation']['monotonic_us']-r[a-1]['event_observation']['monotonic_us'],3600000000)
   self.assertLessEqual(abs(v[b-1]-v[a-1]),27)
 def test_all_emitted_edges_contain_valid_noisy_trajectories(self):
  rng=random.Random(61)
  for trial in range(40):
   r=self.rows(range(0,3601,30));truth=[D(i)/20 for i in range(len(r))]
   # Independent endpoint errors within +/-3 imply movement error <=6.
   values=[x+D(rng.randrange(-300,301))/100 for x in truth]
   for a,b,lo,hi in self.solve(r,values):
    delta=truth[b-1]-truth[a-1];self.assertLessEqual(lo,delta);self.assertGreaterEqual(hi,delta)
 def test_bound_holds_at_maximum_recent_records(self):
  r=self.rows(range(4097));v=[D(i%7)/10 for i in range(len(r))]
  old=comparisons(r,v,D(6),Budget());new=self.solve(r,v)
  self.assertLessEqual(len(new)-len(old),MAX_COMPARISON_ANCHORS*(MAX_COMPARISON_ANCHORS-1)//2)
 def test_context_churn_stays_bounded(self):
  r=self.rows(range(4097))
  for i,row in enumerate(r):row['event_observation']['context_id']=str(i//2)
  edges=self.solve(r,[D(i%3) for i in range(len(r))])
  self.assertLess(len(edges),4097)
  self.assertTrue(all(r[a-1]['event_observation']['context_id']==r[b-1]['event_observation']['context_id'] for a,b,lo,hi in edges))
 def test_unknown_gap_and_input_values_are_unchanged(self):
  r=self.rows([0,10,60,180,3600]);v=list(map(D,[10,10,11,11,12]));before=copy.deepcopy((r,v))
  self.solve(r,v);self.assertEqual((r,v),before)
 def test_budget_exhaustion_aborts(self):
  with patch('daily_constraints.MAX_WORK',0),self.assertRaises(WorkLimit):self.solve(self.rows([0,10]),[0,0])
 def test_larger_allowance_never_tightens_edges(self):
  r=self.rows([0,10,130,140]);v=list(map(D,[10,14,11,9]))
  a=self.solve(r,v);b=recent_comparisons(r,v,D(7),Budget())
  self.assertEqual(len(a),len(b))
  for x,y in zip(a,b):self.assertEqual(x[:2],y[:2]);self.assertLessEqual(y[2],x[2]);self.assertGreaterEqual(y[3],x[3])
