"""Synthetic control/provenance tests. Never real-camera or reading accuracy."""
from datetime import datetime, timedelta, timezone
from email.message import Message
import hashlib, json, unittest
from io import BytesIO

import numpy as np
from PIL import Image

from auto_capture import Choice, MAX_SHOTS, Quality, TuneFailure, measure, tune
from auto_preview import capabilities, receipt, request


def image(level=190, contrast=110, glare=0, size=(640, 480)):
    pixels = np.full((size[1], size[0]), level, dtype=np.uint8)
    # Alternating stripes ensure the fixture has detail; not a fake meter label.
    pixels[:, :size[0] // 4] = max(0, level - contrast)
    pixels[:int(size[1] * glare), :] = 255
    stream = BytesIO()
    Image.fromarray(pixels).save(stream, format='JPEG', quality=95)
    return stream.getvalue()


class FakeProbe:
    def __init__(self, render=None):
        self.calls = []
        self.deadlines = []
        self.render = render or (lambda choice: image())
        self.patch = lambda headers, index: None
        self.utc = datetime(2026, 9, 22, tzinfo=timezone.utc)
        self.failure = None
        self.on_call = lambda: None
        self.orientation = 0

    def __call__(self, choice, deadline):
        self.calls.append(choice)
        self.deadlines.append(deadline)
        self.on_call()
        if self.failure:
            raise self.failure
        blob = self.render(choice)
        count = len(self.calls)
        headers = Message()
        for key, value in {'X-AIEdge-Frame-Id': 'frame-' + str(count),
                           'X-AIEdge-SHA256': hashlib.sha256(blob).hexdigest(),
                           'X-AIEdge-Captured-At': (self.utc + timedelta(seconds=count)).isoformat(),
                           'X-AIEdge-Clock-Id': 'same-boot',
                           'X-AIEdge-Capture-Monotonic-Us': str(count * 1000000),
                           'X-AIEdge-Image-Orientation': str(self.orientation)}.items():
            headers[key] = value
        self.patch(headers, count)
        return blob, headers


class QualityTests(unittest.TestCase):
    def test_clean_image_and_not_accuracy(self):
        quality = measure(image())
        self.assertTrue(quality.accepted)
        self.assertFalse(quality.report()['accuracy_verified'])

    def test_dark_white_blank_and_glare_rejected(self):
        for blob, reason in ((image(75), 'too_dark'), (image(245), 'too_bright'),
                             (image(190, 0), 'low_contrast'), (image(glare=.08), 'clipped_highlights')):
            with self.subTest(reason=reason):
                quality = measure(blob)
                self.assertFalse(quality.accepted)
                self.assertIn(reason, quality.reasons)

    def test_one_bad_region_not_hidden_by_good_regions(self):
        quality = measure(image(), [(0, 0, 120, 120), (160, 0, 480, 480)])
        self.assertFalse(quality.accepted)
        self.assertIn('low_contrast', quality.reasons)

    def test_bad_input_geometry_rejected_before_probe(self):
        for regions in ('', None, [(True, 0, 100, 100)], [(0, 0, 641, 100)], [(0, 0, 20, 100)],
                        [(0, 0, 100, 100)] * 33, [(0, 0, 100)], [(0, 400, 100, 100)]):
            probe = FakeProbe()
            with self.subTest(regions=regions), self.assertRaisesRegex(ValueError, 'auto_regions_invalid'):
                tune(probe, regions=regions)
            self.assertEqual(probe.calls, [])

    def test_bad_images_rejected(self):
        for blob in (b'not a jpeg', b'\xff\xd8broken\xff\xd9', image(size=(320, 240)),
                     image()[:-2], bytearray(image())):
            with self.subTest(size=len(blob)), self.assertRaisesRegex(ValueError, 'auto_image_invalid'):
                measure(blob)


class TuneTests(unittest.TestCase):
    def test_accepted_lower_light_comparison_returns_candidate_only(self):
        probe = FakeProbe()
        result = tune(probe)
        self.assertEqual(probe.calls, [Choice(50, 300), Choice(25, 300)])
        self.assertEqual(result.selected.choice, Choice(25, 300))
        report = result.report()
        self.assertEqual(report['state'], 'candidate')
        for field in ('saved', 'physical_behavior_verified', 'accuracy_verified', 'training_allowed'):
            self.assertIs(report[field], False)
        self.assertFalse(report['shots'][0]['training_allowed'])

    def test_dark_comparison_keeps_previous_good_image(self):
        probe = FakeProbe(lambda choice: image(190 if choice.intensity == 50 else 90))
        result = tune(probe)
        self.assertEqual(result.selected.choice.intensity, 50)
        self.assertEqual(len(result.shots), 2)

    def test_dark_scene_uses_light_before_exposure_never_gain(self):
        probe = FakeProbe(lambda choice: image(min(190, int(choice.intensity * choice.exposure / 240))))
        result = tune(probe)
        self.assertEqual(probe.calls, [Choice(50, 300), Choice(100, 300), Choice(100, 600)])
        self.assertEqual(result.selected.choice, Choice(100, 600))
        for choice in probe.calls:
            self.assertEqual(choice.controls(0)['gain'], 0)
            self.assertFalse(choice.controls(0)['auto_gain'])
            self.assertFalse(choice.controls(0)['auto_exposure'])

    def test_overexposed_scene_reduces_exposure(self):
        probe = FakeProbe(lambda choice: image(245 if choice.exposure >= 300 else 190))
        result = tune(probe)
        self.assertEqual(result.selected.choice, Choice(50, 180))

    def test_unusable_scene_terminates_without_repeating_a_choice(self):
        probe = FakeProbe(lambda choice: image(20))
        with self.assertRaisesRegex(TuneFailure, 'auto_no_usable_image') as caught:
            tune(probe)
        self.assertLessEqual(len(probe.calls), MAX_SHOTS)
        self.assertEqual(len(set(probe.calls)), len(probe.calls))
        self.assertEqual(len(caught.exception.shots), len(probe.calls))

    def test_eight_shot_limit_even_if_highlights_do_not_improve(self):
        probe = FakeProbe(lambda choice: image(255, glare=.5))
        with self.assertRaisesRegex(TuneFailure, 'auto_no_usable_image'):
            tune(probe, seed=Choice(100, 1200))
        self.assertEqual(len(probe.calls), MAX_SHOTS)

    def test_blank_scene_is_not_repaired_by_more_captures(self):
        probe = FakeProbe(lambda choice: image(190, 0))
        with self.assertRaisesRegex(TuneFailure, 'auto_no_usable_image'):
            tune(probe)
        self.assertEqual(len(probe.calls), 1)

    def test_deadline_passed_to_probe_and_checked_after_return(self):
        ticks = [100]
        probe = FakeProbe()
        probe.on_call = lambda: ticks.__setitem__(0, 190)
        with self.assertRaisesRegex(TuneFailure, 'auto_deadline') as caught:
            tune(probe, clock=lambda: ticks[0])
        self.assertEqual(len(probe.calls), 1)
        self.assertEqual(len(caught.exception.shots), 1)
        self.assertEqual(probe.deadlines, [190])

    def test_cancel_before_or_during_capture_is_bounded(self):
        flag = [True]
        probe = FakeProbe()
        with self.assertRaisesRegex(TuneFailure, 'auto_cancelled'):
            tune(probe, cancelled=lambda: flag[0])
        self.assertEqual(probe.calls, [])
        flag[0] = False
        probe.on_call = lambda: flag.__setitem__(0, True)
        with self.assertRaisesRegex(TuneFailure, 'auto_cancelled') as caught:
            tune(probe, cancelled=lambda: flag[0])
        self.assertEqual(len(probe.calls), 1)
        self.assertEqual(len(caught.exception.shots), 1)

    def test_unknown_exceptions_are_sanitized_and_not_retried(self):
        probe = FakeProbe()
        probe.failure = OSError('http://user:SECRET@camera/private')
        with self.assertRaisesRegex(TuneFailure, '^auto_probe_failed$') as caught:
            tune(probe)
        self.assertEqual(len(probe.calls), 1)
        self.assertNotIn('SECRET', str(caught.exception))

    def test_uncertain_restore_retains_prior_shot_and_never_retries(self):
        probe = FakeProbe()
        def progress(count, quality):
            probe.failure = ValueError('auto_restore_unverified')
        with self.assertRaisesRegex(TuneFailure, 'auto_restore_unverified') as caught:
            tune(probe, progress=progress)
        self.assertEqual(len(probe.calls), 2)
        self.assertEqual(len(caught.exception.shots), 1)

    def test_replayed_frame_changed_epoch_and_bad_utc_are_rejected(self):
        def patch(name, value):
            def apply(headers, count):
                if count > 1: headers.replace_header(name, value)
            return apply
        for key, value in (('X-AIEdge-Frame-Id', 'frame-1'),
                           ('X-AIEdge-Capture-Monotonic-Us', '1000000'),
                           ('X-AIEdge-Clock-Id', 'new-boot'),
                           ('X-AIEdge-Captured-At', '2026-09-22T00:00:09+00:00')):
            probe = FakeProbe(); probe.patch = patch(key, value)
            with self.subTest(key=key), self.assertRaisesRegex(TuneFailure, 'auto_frame_not_fresh'):
                tune(probe)
            self.assertEqual(len(probe.calls), 2)

    def test_bad_hash_or_orientation_is_not_accepted(self):
        for key, value, code in (('X-AIEdge-SHA256', '0' * 64, 'image_hash_mismatch'),
                                 ('X-AIEdge-Image-Orientation', '1', 'auto_orientation_unverified')):
            probe = FakeProbe(); probe.patch = lambda headers, count: headers.replace_header(key, value)
            with self.subTest(key=key), self.assertRaisesRegex(TuneFailure, code):
                tune(probe)
            self.assertEqual(len(probe.calls), 1)

    def test_identical_jpeg_is_not_new_accuracy_evidence(self):
        result = tune(FakeProbe())
        self.assertEqual(result.shots[0].sha256, result.shots[1].sha256)
        self.assertNotEqual(result.shots[0].frame_id, result.shots[1].frame_id)
        self.assertFalse(result.report()['accuracy_verified'])

    def test_all_orientations_preserved_no_automatic_flip(self):
        for orientation in range(4):
            probe = FakeProbe(); probe.orientation = orientation
            result = tune(probe, orientation)
            self.assertEqual(result.selected.choice.controls(orientation)['mirror'], bool(orientation & 1))
            self.assertEqual(result.selected.choice.controls(orientation)['flip'], bool(orientation & 2))
        for invalid in (True, -1, 4, '0'):
            probe = FakeProbe()
            with self.assertRaisesRegex(ValueError, 'auto_orientation_invalid'):
                tune(probe, invalid)
            self.assertEqual(probe.calls, [])

    def test_invalid_choices_are_not_coerced(self):
        for args in ((True, 300), (0, 300), (101, 300), (50, 29), (50, 1201), (50, 300.0)):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, 'auto_choice_invalid'):
                Choice(*args)
        for seed in (False, 0, {}, '50'):
            probe = FakeProbe()
            with self.subTest(seed=seed), self.assertRaisesRegex(ValueError, 'auto_choice_invalid'):
                tune(probe, seed=seed)
            self.assertEqual(probe.calls, [])

    def test_callback_error_cancel_and_elapsed_time_cannot_return_success(self):
        probe = FakeProbe()
        with self.assertRaisesRegex(TuneFailure, 'auto_progress_failed') as caught:
            tune(probe, progress=lambda count, quality: (_ for _ in ()).throw(OSError('SECRET')))
        self.assertEqual(len(caught.exception.shots), 1)
        ticks = [0]
        probe = FakeProbe()
        with self.assertRaisesRegex(TuneFailure, 'auto_deadline'):
            tune(probe, clock=lambda: ticks[0], progress=lambda count, quality: ticks.__setitem__(0, 90))
        self.assertEqual(len(probe.calls), 1)


class ContractTests(unittest.TestCase):
    CAPS = dict(version=1, model='OV2640', mode='remote-camera', path='/api/v1/capture/temporary',
                method='POST', frame_size=[640, 480], temporary_controls=True,
                restore_before_response=True, sd_writes=0, max_capture_seconds=20)

    def test_capability_cleanup_and_unsupported_contract_has_no_fallback(self):
        self.assertNotIn('private', capabilities(dict(self.CAPS, private='SECRET')))
        for patch in ({'version':True}, {'model':'OV5640'}, {'sd_writes':False}, {'sd_writes':1},
                      {'path':'/config-save'}, {'method':'GET'}, {'restore_before_response':False},
                      {'temporary_controls':1}, {'max_capture_seconds':True}, {'max_capture_seconds':120}):
            with self.subTest(patch=patch), self.assertRaisesRegex(ValueError, 'auto_contract_unsupported'):
                capabilities(dict(self.CAPS, **patch))
        with self.assertRaisesRegex(ValueError, 'auto_contract_unsupported'):
            capabilities(dict(self.CAPS, frame_size=[640.0, 480.0]))

    def test_canonical_request_contains_no_persistent_settings_or_credentials(self):
        body = request(Choice(50, 300), 3, 'a' * 64, 'b' * 32)
        self.assertEqual(body, request(Choice(50, 300), 3, 'a' * 64, 'b' * 32))
        data = json.loads(body)
        self.assertEqual(set(data), {'version', 'base_revision', 'request_id', 'intensity', 'controls'})
        self.assertEqual(data['controls']['gain'], 0)
        self.assertTrue(data['controls']['mirror']); self.assertTrue(data['controls']['flip'])
        for revision, nonce in (('A' * 64, 'b' * 32), ('a' * 63, 'b' * 32), ('a' * 64, 'bad')):
            with self.assertRaisesRegex(ValueError, 'auto_choice_invalid'):
                request(Choice(50, 300), 0, revision, nonce)

    def test_exact_receipt_and_every_missing_field_rejected(self):
        body = request(Choice(50, 300), 0, 'a' * 64, 'b' * 32)
        fields = {'X-AIEdge-Temporary-Request-SHA256': hashlib.sha256(body).hexdigest(),
                  'X-AIEdge-Saved-Revision': 'a' * 64, 'X-AIEdge-Restored-Revision': 'a' * 64,
                  'X-AIEdge-Settings-Restored': 'true', 'X-AIEdge-Light-Off': 'true',
                  'X-AIEdge-Temporary-SD-Writes': '0'}
        receipt(fields, body, 'a' * 64)
        for name in fields:
            headers = dict(fields); del headers[name]
            with self.subTest(name=name), self.assertRaises(ValueError):
                receipt(headers, body, 'a' * 64)
        self.assertRaisesRegex(ValueError, 'auto_receipt_unverified', receipt, fields, body + b' ', 'a' * 64)
        self.assertRaisesRegex(ValueError, 'auto_config_conflict', receipt, fields, body, 'c' * 64)

    def test_duplicate_receipts_and_truthy_values_rejected(self):
        body = request(Choice(50, 300), 0, 'a' * 64, 'b' * 32)
        headers = Message()
        headers['X-AIEdge-Temporary-Request-SHA256'] = hashlib.sha256(body).hexdigest()
        headers['X-AIEdge-Temporary-Request-SHA256'] = hashlib.sha256(body).hexdigest()
        self.assertRaisesRegex(ValueError, 'auto_receipt_unverified', receipt, headers, body, 'a' * 64)
        headers = {'X-AIEdge-Temporary-Request-SHA256': hashlib.sha256(body).hexdigest(),
                   'X-AIEdge-Saved-Revision': 'a' * 64, 'X-AIEdge-Restored-Revision': 'a' * 64,
                   'X-AIEdge-Settings-Restored': '1', 'X-AIEdge-Light-Off': 'true',
                   'X-AIEdge-Temporary-SD-Writes': '0'}
        self.assertRaisesRegex(ValueError, 'auto_restore_unverified', receipt, headers, body, 'a' * 64)


if __name__ == '__main__':
    unittest.main()
