import unittest

from chart_gap_flow import estimate


class GapFlowTests(unittest.TestCase):
    def flow(self,before,after,seconds=600):
        return estimate(before,after,seconds,5,1000,.05,10,775/3600)

    def test_quiet_pointers_select_small_change_with_separate_error_ranges(self):
        model=self.flow([(950,4.95),(950.2,4.96)],[(950.3,.17),(950.2,.18)])
        self.assertAlmostEqual(model['use'],.21)
        self.assertAlmostEqual(model['selected_bounds'][1],.31)
        self.assertGreater(model['bounds'][1],10)

    def test_coarse_whole_turn_and_disagreeing_flanks_do_not_imply_zero(self):
        self.assertIsNone(self.flow([(950,1),(950,1)],[(955,1),(955,1)]))
        self.assertIsNone(self.flow([(950,1),(950,2)],[(950,2),(950,2)]))
        self.assertIsNone(self.flow([(950,1)],[(950,1),(950,1)]))

    def test_short_interval_single_feasible_count_accepts_measured_motion(self):
        self.assertAlmostEqual(self.flow([(950,4.8)],[(950.4,.2)],5)['use'],.4)
        self.assertIsNone(self.flow([(950,1)],[(950,3)],5))

    def test_ambiguous_coarse_wrap_is_withheld(self):
        self.assertIsNone(self.flow([(0,0),(0,0)],[(0,0),(0,0)],4800))

    def test_compact_neighbors_can_check_motion_without_a_slower_dial(self):
        before = [(None,4.99),(None,4.99),(971.58,4.9916)]
        after = [(971.33,4.9928),(971.11,4.9905),(None,4.991)]
        motion = self.flow(before,after,502)
        self.assertAlmostEqual(motion['use'],.0012)
        self.assertGreater(motion['bounds'][1],5)
        self.assertIsNone(self.flow(before, [after[0],(None,4.99)],502))
        self.assertIsNone(self.flow([(None,4.6),before[-1]],after,502))

    def test_meter_capacity_allows_half_a_turn_but_photos_exclude_a_whole_turn(self):
        model = estimate([(950,1),(950,1)],[(950,1),(950,1)],1248,5,1000,.05,10,1700/3600)
        self.assertEqual(model['use'],0)
        self.assertGreater(model['bounds'][1],0)

    def test_coarse_requires_flow_above_ceiling(self):
        self.assertIsNone(self.flow([(0,0)],[(21.1,1.05)],5))
