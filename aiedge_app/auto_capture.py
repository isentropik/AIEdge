"""Bounded exposure/light search. No camera I/O, configuration writes or labels.

The supplied probe must enforce the absolute deadline and prove it restored the
saved camera settings before returning. JPEG statistics are image-quality
heuristics, never recognition accuracy or a measurement of sensor noise.
"""
from dataclasses import dataclass
from io import BytesIO
import time

import numpy as np
from PIL import Image

from capture import MAX_IMAGE, validate, camera_header
import capture_clock

MAX_SHOTS = 8
MAX_SECONDS = 90


@dataclass(frozen=True)
class Choice:
    intensity: int
    exposure: int

    def __post_init__(self):
        if type(self.intensity) is not int or not 1 <= self.intensity <= 100 \
                or type(self.exposure) is not int or not 30 <= self.exposure <= 1200:
            raise ValueError('auto_choice_invalid')

    def controls(self, orientation):
        if type(orientation) is not int or orientation not in range(4):
            raise ValueError('auto_orientation_invalid')
        # Gain stays at the sensor's zero setting. Never amplify a dark image
        # to make its histogram look better. Exposure units are driver units.
        return dict(auto_exposure=False, dsp_exposure=False, exposure=self.exposure,
                    compensation=0, auto_gain=False, gain=0, gain_limit=0,
                    mirror=bool(orientation & 1), flip=bool(orientation & 2))


@dataclass(frozen=True)
class Quality:
    level: float
    contrast: float
    clipped: float
    accepted: bool
    reasons: tuple

    def report(self):
        return dict(level=round(self.level, 3), contrast=round(self.contrast, 3),
                    clipped_fraction=round(self.clipped, 6), accepted=self.accepted,
                    reasons=list(self.reasons), accuracy_verified=False)


def validate_regions(regions):
    if not isinstance(regions, (tuple, list)) or len(regions) > 32:
        raise ValueError('auto_regions_invalid')
    for box in regions:
        if not isinstance(box, (tuple, list)) or len(box) != 4 \
                or any(type(v) is not int for v in box):
            raise ValueError('auto_regions_invalid')
        x, y, w, h = box
        if x < 0 or y < 0 or w < 32 or h < 32 or x + w > 640 or y + h > 480:
            raise ValueError('auto_regions_invalid')


def measure(blob, regions=()):
    """Use one small luminance sample per region, retaining the worst result.

    Optional rectangles are current-image coordinates supplied by a caller
    that has verified geometry. Old reference crops must not be used blindly.
    Without rectangles the full scene is scored; a human still checks it.
    """
    if not isinstance(blob, bytes) or not 4 <= len(blob) <= MAX_IMAGE \
            or not blob.startswith(b'\xff\xd8') or not blob.endswith(b'\xff\xd9'):
        raise ValueError('auto_image_invalid')
    validate_regions(regions)
    boxes = list(regions) or [(0, 0, 640, 480)]
    try:
        with Image.open(BytesIO(blob)) as image:
            if image.format != 'JPEG' or image.size != (640, 480):
                raise ValueError('auto_image_invalid')
            image.load()
            gray = image.convert('L')
    except (OSError, Image.DecompressionBombError):
        raise ValueError('auto_image_invalid') from None
    metrics = []
    for x, y, w, h in boxes:
        # Box averaging reduces cost and individual hot pixels. Saturation is
        # checked BEFORE averaging so small glare patches are not hidden.
        region = gray.crop((x, y, x + w, y + h))
        raw = np.asarray(region, dtype=np.uint8)
        clipped = float(np.mean(raw >= 250))
        sample = np.asarray(region.resize((min(160, w), min(120, h)), Image.Resampling.BOX), dtype=np.float32)
        low, high = (float(v) for v in np.percentile(sample, (15, 85)))
        metrics.append((high, high - low, clipped))
    level = min(m[0] for m in metrics)
    contrast = min(m[1] for m in metrics)
    clipped = max(m[2] for m in metrics)
    reasons = tuple(name for condition, name in
                    ((level < 145, 'too_dark'), (any(m[0] > 225 for m in metrics), 'too_bright'),
                     (contrast < 35, 'low_contrast'), (clipped > .04, 'clipped_highlights')) if condition)
    return Quality(level, contrast, clipped, not reasons, reasons)


@dataclass(frozen=True)
class Shot:
    choice: Choice
    blob: bytes
    headers: object
    quality: Quality
    frame_id: str
    sha256: str
    captured_at: str
    clock_id: str
    monotonic_us: int

    def report(self):
        return dict(intensity=self.choice.intensity, exposure=self.choice.exposure,
                    gain=0, frame_id=self.frame_id, sha256=self.sha256,
                    captured_at=self.captured_at, clock_id=self.clock_id,
                    monotonic_us=self.monotonic_us, quality=self.quality.report(),
                    training_allowed=False, accuracy_verified=False)


def verified_shot(choice, blob, headers, orientation, regions=()):
    frame, stamp, digest = validate(blob, headers)
    clock = capture_clock.parse(headers)
    if clock is None:
        raise ValueError('auto_clock_unverified')
    if camera_header(headers, 'X-AIEdge-Image-Orientation') != str(orientation):
        raise ValueError('auto_orientation_unverified')
    return Shot(choice, blob, headers, measure(blob, regions), frame, digest, stamp,
                clock[0], clock[1])


class TuneFailure(ValueError):
    """Retain verified test shots for the caller's diagnostic/exclusion store."""
    def __init__(self, code, shots=()):
        super().__init__(code)
        self.shots = tuple(shots)


@dataclass(frozen=True)
class Result:
    selected: Shot
    shots: tuple

    def report(self):
        return dict(state='candidate', selected=self.selected.report(),
                    shots=[shot.report() for shot in self.shots],
                    saved=False, physical_behavior_verified=False,
                    accuracy_verified=False, training_allowed=False)


def _next(choice, quality):
    # A mix of dark regions and clipping suggests uneven illumination: do not
    # keep increasing exposure. The bounded search will reject the scene.
    brighter = quality.level < 145 and quality.clipped <= .04 \
        and 'too_bright' not in quality.reasons
    if brighter:
        if choice.intensity < 100:
            return Choice(min(100, choice.intensity * 2), choice.exposure)
        return Choice(100, min(1200, choice.exposure * 2))
    if 'too_bright' in quality.reasons or 'clipped_highlights' in quality.reasons:
        if choice.exposure > 30:
            return Choice(choice.intensity, max(30, int(choice.exposure * .6)))
        return Choice(max(1, int(choice.intensity * .6)), 30)
    # Light/exposure cannot repair a blank or obscured scene.
    return choice


def tune(probe, orientation=0, regions=(), seed=None, *, clock=time.monotonic,
         cancelled=lambda: False, progress=lambda count, quality: None):
    """At most eight distinct temporary captures, within one 90-second budget.

    Callback probe(choice, absolute_deadline) returns a JPEG/header pair after
    checking a temporary-settings receipt. No retry follows an uncertain call.
    No selected setting is committed here. Only an accepted shot is returned.
    """
    choice = Choice(50, 300) if seed is None else seed
    if not isinstance(choice, Choice):
        raise ValueError('auto_choice_invalid')
    choice.controls(orientation)
    # Validate rectangles before any camera request, even if a later JPEG fails.
    validate_regions(regions)
    shots, tried = [], set()
    deadline = clock() + MAX_SECONDS
    best = None
    for _ in range(MAX_SHOTS):
        if cancelled():
            raise TuneFailure('auto_cancelled', shots)
        if clock() >= deadline:
            raise TuneFailure('auto_deadline', shots)
        if choice in tried:
            break
        tried.add(choice)
        try:
            blob, headers = probe(choice, deadline)
            shot = verified_shot(choice, blob, headers, orientation, regions)
            if shots and (shot.clock_id != shots[0].clock_id or shot.monotonic_us <= shots[-1].monotonic_us
                          or any(shot.frame_id == old.frame_id for old in shots)):
                raise ValueError('auto_frame_not_fresh')
            if shots and capture_clock.interval(dict(shots[-1].report(), camera='probe'),
                                                dict(shot.report(), camera='probe'))['state'] != 'continuous':
                raise ValueError('auto_frame_not_fresh')
        except Exception as error:
            # Arbitrary exception text can contain device credentials/URLs.
            code = str(error) if isinstance(error, ValueError) and str(error) in {
                'auto_receipt_unverified', 'auto_restore_unverified', 'auto_config_conflict',
                'auto_contract_unsupported', 'auto_image_invalid', 'auto_clock_unverified',
                'auto_orientation_unverified', 'auto_frame_not_fresh', 'auto_deadline',
                'camera_busy', 'camera_timeout', 'camera_authentication_failed',
                'image_hash_mismatch', 'duplicate_camera_header'} else 'auto_probe_failed'
            raise TuneFailure(code, shots) from None
        shots.append(shot)
        if cancelled():
            raise TuneFailure('auto_cancelled', shots)
        if clock() >= deadline:
            raise TuneFailure('auto_deadline', shots)
        try:
            progress(len(shots), shot.quality.report())
        except Exception:
            raise TuneFailure('auto_progress_failed', shots) from None
        if cancelled():
            raise TuneFailure('auto_cancelled', shots)
        if clock() >= deadline:
            raise TuneFailure('auto_deadline', shots)
        if shot.quality.accepted:
            best = shot
            # One lower-light comparison where possible. We do not increase
            # gain or exposure to compensate; reject it if it becomes dark.
            if len(shots) == 1 and choice.intensity > 1:
                choice = Choice(max(1, choice.intensity // 2), choice.exposure)
                continue
            return Result(shot, tuple(shots))
        if best is not None:
            return Result(best, tuple(shots))
        choice = _next(choice, shot.quality)
    if best is not None:
        return Result(best, tuple(shots))
    raise TuneFailure('auto_no_usable_image', shots)
