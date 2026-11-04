import unittest
from datetime import date, timezone
from daily_range import daily_range


class CalendarRangeTest(unittest.TestCase):
    def row(self, sec, lo, hi, clock="boot"):
        minute = "2026-11-03T23:59:59" if sec == 0 else "2026-11-04T00:00:%02d" % (sec - 1)
        source = dict(event_id=sec+1, captured_at=minute+"+00:00", monotonic_us=sec*1000000,
                      camera="meter", clock_id=clock, format_id="f", context_id="c")
        return dict(unit="ft3", event_observation=source, absolute=dict(unit="ft3",
                    provenance="temporal_consumption_bounds", bounds=dict(state="bounded",
                    wraps_register=False, ranges=[dict(lower=lo, upper=hi)])))

    def solve(self, *rows):
        return daily_range(rows, date(2026,11,4), timezone.utc,
                          dict(unit="ft3", maximum_rate_per_second=1,
                               dials=[dict(value_per_revolution=1000)]), "f")

    def test_bracket_preserves_uncertainty(self):
        result = self.solve(self.row(0,100,100), self.row(2,102,102), self.row(6,105,105))
        self.assertEqual((result["lower"], result["upper"]), ("3.00", "5.00"))

    def test_missing_midnight(self):
        with self.assertRaisesRegex(ValueError, "bracketing"):
            self.solve(self.row(2,102,102))

    def test_rollover(self):
        with self.assertRaisesRegex(ValueError, "rollover"):
            self.solve(self.row(0,999,999), self.row(2,0,1))

    def test_clock_change(self):
        with self.assertRaisesRegex(ValueError, "source changed"):
            self.solve(self.row(0,100,100), self.row(2,101,101,"restarted"))

    def test_contradiction(self):
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            self.solve(self.row(0,100,100), self.row(2,105,105))

    def test_disjoint_segments_sum_only_observed_minimum(self):
        rows = [self.row(t, 100, 180) for t in (0, 2, 4, 8, 10)]
        # Two measured 2-foot advances, with four seconds between their segments.
        for row, seg, amount in zip(rows[1:], ("a","a","b","b"), (0,2,0,2)):
            row.update(segment_id=seg, anchor_captured_at=seg, minimum=amount,
                       maximum=amount, upper_unbounded=False)
        result = self.solve(*rows)
        self.assertEqual((result["lower"], result["upper"]), ("4.00","10.00"))

    def test_backdated_row_after_midnight_cannot_replace_the_bracket(self):
        with self.assertRaisesRegex(ValueError,"unordered"):
            self.solve(self.row(0,100,101), self.row(2,101,102), self.row(0,100,101))
