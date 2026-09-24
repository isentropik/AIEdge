import unittest
from update import merge,active_intervals
class TimeTests(unittest.TestCase):
 def test_overlap_counted_once(self):self.assertEqual(merge([(0,10),(5,15),(15,20),(30,40)]),[[0,20],[30,40]])
 def test_idle_excluded(self):self.assertEqual(active_intervals([0,60,1000,1060]),[(0,60),(1000,1060)])
 def test_duplicate_events(self):self.assertEqual(active_intervals([60,0,60]),[(0,60)])
if __name__=='__main__':unittest.main()
