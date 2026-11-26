import time
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

import compact_capture as compact
from capture_recovery import BodyTimeout
import test_compact_capture as fixtures


class Reply(BytesIO):
    status = 200

    def __init__(self, body, metadata, *, truncated=False):
        super().__init__(body)
        self.headers = fixtures.headers(metadata)
        self.truncated = truncated

    def read1(self, count):
        data = super().read(count)
        if not data and self.truncated:
            raise TimeoutError()
        return data


class ResumeTests(unittest.TestCase):
    setUp = fixtures.CompactTests.setUp

    def run_capture(self, *, missing=526, feature=True, fault=None):
        payload = self.data
        sha = compact.digest(payload)
        self.calls = []
        self.deadlines = []

        def open_request(req, timeout):
            offset = req.get_header('X-aiedge-offset')
            self.calls.append((req.get_method(), req.selector, offset))
            if req.get_method() == 'POST':
                fields = {'Content-Type': 'application/x-aiedge-q25', 'Content-Length': len(payload),
                          'X-AIEdge-Anchor': '1', 'X-AIEdge-SHA256': sha}
                if feature:
                    fields['X-AIEdge-Compact-Replay'] = '1'
                return Reply(payload[:len(payload)-missing], fields, truncated=True)
            self.assertEqual(req.selector, '/api/v1/compact/part')
            self.assertEqual(req.get_header('X-aiedge-sha256'), sha)
            self.deadlines.append(req.aiedge_deadline)
            begin = int(offset)
            body = payload[begin:begin+compact.REPLAY_CHUNK]
            fields = {'Content-Type': 'application/octet-stream', 'Content-Length': len(body),
                      'X-AIEdge-SHA256': sha, 'X-AIEdge-Offset': offset, 'X-AIEdge-Size': len(payload)}
            if fault == 'absent':
                raise HTTPError(req.full_url, 404, 'missing', fixtures.headers({}), BytesIO())
            if fault == 'timeout':
                raise TimeoutError()
            if fault == 'wrong_bytes':
                body = bytes([body[0] ^ 1]) + body[1:]
            if fault == 'short':
                body = body[:-1]
            if fault == 'short_header':
                body = body[:-1]
                fields['Content-Length'] = len(body)
            if fault in fields:
                fields[fault] = 'wrong'
            return Reply(body, fields)

        with patch.object(self.camera.opener, 'open', side_effect=open_request):
            return self.worker.collect(time.monotonic())

    def test_recovers_same_exposure_and_original_anchor(self):
        self.assertTrue(self.run_capture())
        self.assertEqual(self.calls, [('POST', '/api/v1/compact', None),
                                     ('GET', '/api/v1/compact/part', str(len(self.data)-526))])
        self.assertEqual(self.worker.timing['compact_bytes_recovered'], 526)
        self.assertTrue(self.worker.timing['compact_replay_available'])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT packet,anchor FROM compact_exposures').fetchall(), [(self.data,1)])

    def test_healthy_response_reports_whether_the_camera_can_replay(self):
        for feature in (False, True):
            with self.subTest(feature=feature):
                self.data, self.image = fixtures.packet(tick=1000+int(feature))
                self.assertTrue(self.run_capture(missing=0, feature=feature))
                self.assertEqual(self.calls, [('POST', '/api/v1/compact', None)])
                self.assertEqual(self.worker.timing['compact_replay_available'], feature)
                self.assertNotIn('compact_bytes_recovered', self.worker.timing)

    def test_zero_prefix_part_reads_share_one_deadline(self):
        self.assertTrue(self.run_capture(missing=len(self.data)))
        self.assertGreater(len(self.deadlines), 1)
        self.assertEqual(len(set(self.deadlines)), 1)
        self.assertEqual(sum(method == 'POST' for method, _, _ in self.calls), 1)

    def test_legacy_camera_preserves_initial_failure(self):
        with self.assertRaises(BodyTimeout) as caught:
            self.run_capture(feature=False)
        self.assertEqual(caught.exception.evidence['received_bytes'], len(self.data)-526)
        self.assertEqual(len(self.calls), 1)

    def test_failed_recovery_retains_the_exact_transfer_boundary(self):
        for fault in ('absent', 'timeout', 'short', 'short_header', 'wrong_bytes', 'X-AIEdge-Offset',
                      'X-AIEdge-SHA256', 'X-AIEdge-Size', 'Content-Type'):
            with self.subTest(fault=fault), self.assertRaises(BodyTimeout) as caught:
                self.run_capture(fault=fault)
            self.assertEqual(caught.exception.evidence, {'stage':'compact_body', 'expected_bytes':len(self.data),
                             'received_bytes':len(self.data)-526, 'expected_sha256':compact.digest(self.data)})
            self.assertEqual([method for method, _, _ in self.calls], ['POST', 'GET'])
            self.assertEqual(self.store.status()['captures'], 0)
