import unittest
from performance import Timings


class ReadTimingTests(unittest.TestCase):
    def test_timeout_survives_between_observations_and_excludes_reference_requests(self):
        timings = Timings(clock=lambda: 1)
        def snapshot():
            return timings.snapshot()['transfer_reads']
        self.assertIsNone(snapshot()['last_capture_body_timeout'])
        with self.assertRaises(TimeoutError), timings.transfer_reads(30031):
            raise TimeoutError()
        class Response:
            def read1(self, size):
                return b'x' * size
        for _ in range(182):
            with timings.transfer_reads(4) as reads:
                reads.read1(Response(), 4)
        with self.assertRaises(TimeoutError), timings.transfer_reads(99, reference=True):
            raise TimeoutError()
        data = snapshot()
        self.assertEqual(len(data['samples']), 8)
        self.assertEqual(data['samples'][0]['sequence'], 177)
        self.assertEqual(data['last_capture_body_timeout']['sequence'], 1)
        data['last_capture_body_timeout']['sequence'] = -1
        self.assertEqual(snapshot()['last_capture_body_timeout']['sequence'], 1)
        with self.assertRaises(TimeoutError), timings.transfer_reads(30000):
            raise TimeoutError()
        self.assertEqual(snapshot()['last_capture_body_timeout']['sequence'], 185)

    def test_progress_and_final_stall_are_separate_and_exception_is_preserved(self):
        ticks = iter((0, 0, 2, 2, 5, 5, 20, 20))
        timings = Timings(clock=lambda: next(ticks))
        original = TimeoutError('fixture')

        class Response:
            count = 0
            def read1(self, size):
                self.count += 1
                if self.count == 3:
                    raise original
                return b'abc'

        response = Response()
        with self.assertRaises(TimeoutError) as caught:
            with timings.transfer_reads(9) as trace:
                self.assertEqual(trace.read1(response, 9), b'abc')
                self.assertEqual(trace.read1(response, 6), b'abc')
                trace.read1(response, 3)
        self.assertIs(caught.exception, original)
        row = timings.snapshot()['transfer_reads']['samples'][0]
        self.assertEqual(row, dict(expected_bytes=9, application_bytes=6,
            reference=False, read_calls=3, outcome='timeout', elapsed_seconds=20,
            maximum_read_wait_seconds=15, first_delivery_seconds=2,
            since_last_delivery_seconds=15, sequence=1))

    def test_complete_body_has_no_wait_for_eof(self):
        ticks = iter((0, 1, 2, 2))
        timings = Timings(clock=lambda: next(ticks))
        class Response:
            def read1(self, size):
                self.size = size
                return b'abcd'
        response = Response()
        with timings.transfer_reads(4, reference=True) as trace:
            self.assertEqual(trace.read1(response, 4), b'abcd')
        row = timings.snapshot()['transfer_reads']['samples'][0]
        self.assertEqual(response.size, 4)
        self.assertEqual((row['outcome'], row['read_calls'], row['reference']),
                         ('complete', 1, True))

    def test_empty_body_failure_and_no_delivery_have_no_invented_timing(self):
        timings = Timings(clock=lambda: 5)
        with self.assertRaisesRegex(ValueError, 'fixture'):
            with timings.transfer_reads(4):
                raise ValueError('fixture')
        row = timings.snapshot()['transfer_reads']['samples'][0]
        self.assertEqual(row['outcome'], 'failure')
        self.assertIsNone(row['first_delivery_seconds'])
        self.assertIsNone(row['since_last_delivery_seconds'])
        self.assertEqual(row['application_bytes'], 0)

    def test_window_is_bounded_and_snapshots_do_not_expose_internal_objects(self):
        timings = Timings(clock=lambda: 5)
        for _ in range(10):
            with timings.transfer_reads(4):
                pass
        snapshot = timings.snapshot()['transfer_reads']
        self.assertEqual(snapshot['count_since_start'], 10)
        self.assertEqual([row['sequence'] for row in snapshot['samples']], list(range(3, 11)))
        snapshot['samples'][0]['application_bytes'] = 999
        self.assertEqual(timings.snapshot()['transfer_reads']['samples'][0]['application_bytes'], 0)
        self.assertFalse(snapshot['tcp_packet_timing_measured'])
        self.assertFalse(snapshot['camera_internal_timing_measured'])


if __name__ == '__main__':
    unittest.main()
