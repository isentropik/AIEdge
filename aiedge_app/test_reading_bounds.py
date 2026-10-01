import copy, math, os, random, unittest
from datetime import datetime, timezone
from reading_bounds import display_bounds, feasible_ranges
from reading_format import ReadingFormat
from test_reading_format import document, observation


class BoundTests(unittest.TestCase):
    def test_all_possible_five_unit_turns_are_kept_separate(self):
        result = display_bounds(document([1000, 5], [.1, .01]), [1.095, 9])
        self.assertEqual(result['state'], 'bounded')
        ranges = result['ranges']
        self.assertEqual(len(ranges), 5)
        # The first and last wheel bands intersect the coarse bound only in
        # part; endpoints still count as feasible rather than being discarded.
        for row, centre in zip(ranges, [99.5, 104.5, 109.5, 114.5, 119.5]):
            self.assertLessEqual(row['lower'], centre)
            self.assertGreaterEqual(row['upper'], centre)
            self.assertLess(row['upper'] - row['lower'], .011)
        self.assertFalse(result['accuracy_verified'])
        self.assertFalse(result['training_allowed'])

    def test_full_register_carries_and_leading_zero(self):
        scales = [10000000, 1000000, 100000, 10000, 1000, 5]
        positions = [.2578231394, 2.65378594398, 5.61773014069, 5.74945545197, 8.07364940643, 6.11219596863]
        d = document(scales, [.1] * 6)
        before = copy.deepcopy(d)
        result = display_bounds(d, positions)
        self.assertEqual(len(result['ranges']), 4)
        for row, centre in zip(result['ranges'], [255798.0561, 255803.0561, 255808.0561, 255813.0561]):
            self.assertLess(row['lower'], centre)
            self.assertGreater(row['upper'], centre)
            self.assertTrue(row['lower_text'].startswith('0255'))
        self.assertEqual(d, before)
        self.assertEqual(result['common_integer_prefix'],'0255')

    def test_register_wrap_is_two_ranges_not_a_near_full_register(self):
        result = display_bounds(document([1000, 100], [.01, .01]), [0, 0])
        self.assertTrue(result['wraps_register'])
        self.assertEqual(len(result['ranges']), 2)
        self.assertEqual(result['ranges'][0]['lower'], 0)
        self.assertEqual(result['ranges'][-1]['upper'], 1000)
        self.assertEqual(result['ranges'][-1]['upper_text'], '1000.0')
        self.assertEqual(result['common_integer_prefix'],'')

    def test_shared_prefix_is_calculated_from_this_frame_including_carries(self):
        scales=[10000000,1000000,100000,10000,1000,5]
        d=document(scales,[.1]*6)
        for total,prefix in ((255845,'02558'),(255945,'02559'),(999945,'09999')):
            positions=[(total%period)/period*10 for period in scales]
            result=display_bounds(d,positions)
            self.assertEqual(result['common_integer_prefix'],prefix)

    def test_large_dial_contradiction_is_checked_after_small_wheel_aliases(self):
        result = feasible_ranges([10000, 1000, 5], [9, 1, 0], [.01, .1, .01])
        self.assertEqual(result, {'state': 'inconsistent', 'reason': 'dial_bounds_disagree'})

    def test_outward_display_rounding_does_not_exclude_endpoints(self):
        result = display_bounds(document([1000, 5], [.1, .01]), [1.095, 9])
        for row in result['ranges']:
            self.assertLessEqual(float(row['lower_text']), row['lower'])
            self.assertGreaterEqual(float(row['upper_text']), row['upper'])
            self.assertTrue(math.isfinite(row['lower']) and math.isfinite(row['upper']))

    def test_large_alias_count_is_bounded_without_a_misleading_partial_list(self):
        result = display_bounds(document([1e12, 1e6, 1], [.49] * 3), [5, 5, 5])
        self.assertEqual(result, {'state': 'unavailable', 'reason': 'range_limit'})
        self.assertNotIn('ranges', result)

    def test_small_bands_remain_representable_at_large_totals(self):
        result = display_bounds(document([1e100, 1e99, 1e98], [.01] * 3), [1.234, 2.34, 3.4])
        self.assertEqual(result['state'], 'bounded')
        self.assertTrue(all(math.isfinite(row['lower']) and math.isfinite(row['upper']) for row in result['ranges']))

    def test_independent_circular_residual_oracle_with_non_decimal_ratio(self):
        rng = random.Random(415)
        scales, errors = [100, 20, 2], [.1, .2, .2]
        for scene in range(40):
            total = rng.uniform(0, 100)
            positions = [((total % period) / period * 10 + rng.uniform(-error, error)) % 10
                         for period, error in zip(scales, errors)]
            result = feasible_ranges(scales, positions, errors)
            self.assertEqual(result['state'], 'bounded')
            # Independent test oracle evaluates phase residuals directly. The
            # generated observations exercise math, not real-image accuracy.
            for tick in range(1000):
                candidate = tick / 10
                expected = all(abs((candidate - position * period / 10 + period / 2) % period - period / 2)
                               <= error * period / 10 + 1e-9 for period, position, error in zip(scales, positions, errors))
                included = any(float(lo) - 1e-9 <= candidate <= float(hi) + 1e-9 for lo, hi in result['intervals'])
                self.assertEqual(included, expected, (scene, candidate))


@unittest.skipUnless(os.environ.get('AIEDGE_READING_LIBRARY'), 'reading native library required')
class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from native import Native
        cls.native = Native(os.environ['AIEDGE_READING_LIBRARY'])

    def test_ambiguous_ranges_never_publish_a_point_to_mqtt(self):
        from mqtt_output import fresh_state
        d = document([1000, 5], [.1, .01])
        source = observation([1.095, 9]);source['source_sha256'] = 'b' * 64
        result = ReadingFormat(self.native, d).evaluate(source)
        self.assertEqual(result['state'], 'ambiguous')
        self.assertIsNone(result['value'])
        self.assertNotIn('text', result)
        self.assertEqual(len(result['bounds']['ranges']), 5)
        snapshot = {'reading': result, 'latest': {'sha256': 'b' * 64, 'captured_at': datetime.now(timezone.utc).isoformat()}}
        self.assertIsNone(fresh_state(snapshot, 90))

    def test_early_native_ambiguity_cannot_hide_larger_dial_contradiction(self):
        d = document([10000, 1000, 5], [.01, .1, .01])
        self.assertEqual(self.native.reading([10000, 1000, 5], [9, 1, 0], [.01, .1, .01])['state'], 'ambiguous')
        result = ReadingFormat(self.native, d).evaluate(observation([9, 1, 0]))
        self.assertEqual(result['state'], 'inconsistent')
        self.assertIsNone(result['value'])
        self.assertEqual(result['reason'], 'dial_bounds_disagree')

    def test_resource_limit_retains_ambiguous_state_without_a_point(self):
        result = ReadingFormat(self.native, document([1e12, 1e6, 1], [.49] * 3)).evaluate(observation([5, 5, 5]))
        self.assertEqual(result['state'], 'ambiguous')
        self.assertIsNone(result['value'])
        self.assertEqual(result['bounds']['reason'], 'range_limit')
