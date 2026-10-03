"""Non-destructive framing with exact source-coordinate mapping.

Raw JPEGs and recognition input pixels are never resampled or replaced here.
The rendered preview uses the same affine map used to place source landmarks.
"""
import hashlib
import io
import json
import math
import threading
from copy import deepcopy
from pathlib import Path

from PIL import Image
from calibration_builder import image_rgb
from saved_file import SavedFile

SIZE = (640, 480)
IDENTITY = dict(version=1, turns=0, angle=0, crop=[0, 0, 640, 480])


def strict_json(raw):
    def unique(rows):
        result = {}
        for name, value in rows:
            if name in result:
                raise ValueError('image_edit_invalid')
            result[name] = value
        return result

    def constant(value):
        raise ValueError('image_edit_invalid')

    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=constant)
    except (UnicodeError, RecursionError, json.JSONDecodeError):
        raise ValueError('image_edit_invalid') from None


def inverse(m):
    a, b, c, d, e, f = m
    determinant = a * e - b * d
    if not math.isfinite(determinant) or abs(determinant) < 1e-12:
        raise ValueError('image_edit_invalid')
    return [e / determinant, -b / determinant, (b * f - e * c) / determinant,
            -d / determinant, a / determinant, (d * c - a * f) / determinant]


def point(m, p):
    return [m[0] * p[0] + m[1] * p[1] + m[2],
            m[3] * p[0] + m[4] * p[1] + m[5]]


def corners(box):
    x, y, w, h = box
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


class Edit:
    def __init__(self, value=None):
        value = deepcopy(IDENTITY if value is None else value)
        if not isinstance(value, dict) or set(value) != {'version', 'turns', 'angle', 'crop'} \
                or type(value['version']) is not int or value['version'] != 1 \
                or type(value['turns']) is not int or value['turns'] not in range(4) \
                or type(value['angle']) not in (int, float):
            raise ValueError('image_edit_invalid')
        try:
            angle = float(value['angle'])
        except (OverflowError, ValueError):
            raise ValueError('image_edit_invalid') from None
        if not math.isfinite(angle) or not -15 <= angle <= 15:
            raise ValueError('image_edit_invalid')
        radians = math.radians(90 * value['turns'] + angle)
        co, si = math.cos(radians), math.sin(radians)
        # Quarter turns use exact coefficients and dimensions.
        co, si = (0.0 if abs(v) < 1e-12 else 1.0 if abs(v - 1) < 1e-12
                  else -1.0 if abs(v + 1) < 1e-12 else v for v in (co, si))
        width = math.ceil(abs(co) * 640 + abs(si) * 480)
        height = math.ceil(abs(si) * 640 + abs(co) * 480)
        self.extent = [width, height]
        self.source_to_oriented = [co, -si, width / 2 - co * 320 + si * 240,
                                   si, co, height / 2 - si * 320 - co * 240]
        crop = value['crop']
        if crop is None:
            crop = [0, 0, width, height]
        if not isinstance(crop, list) or len(crop) != 4 or any(type(v) is not int for v in crop):
            raise ValueError('image_edit_invalid')
        x, y, w, h = crop
        if not (16 <= w <= width and 16 <= h <= height and 0 <= x <= width - w and 0 <= y <= height - h):
            raise ValueError('image_crop_outside_frame')
        self.value = dict(version=1, turns=value['turns'], angle=angle, crop=crop)
        self.scale = min(640 / w, 480 / h)
        self.offset = [(640 - w * self.scale) / 2, (480 - h * self.scale) / 2]
        a, b, c, d, e, f = self.source_to_oriented
        s, (ox, oy) = self.scale, self.offset
        self.source_to_view = [a * s, b * s, (c - x) * s + ox,
                               d * s, e * s, (f - y) * s + oy]
        self.view_to_source = inverse(self.source_to_view)
        encoded = json.dumps(self.value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        self.sha256 = hashlib.sha256(encoded).hexdigest()

    def contains_source(self, p, margin=0):
        if not isinstance(p, (tuple, list)) or len(p) != 2 or any(
                type(v) not in (int, float) for v in p):
            return False
        if not 0 <= p[0] <= 640 or not 0 <= p[1] <= 480:
            return False
        if not all(math.isfinite(v) for v in p):
            return False
        q = point(self.source_to_oriented, p)
        x, y, w, h = self.value['crop']
        return x + margin - 1e-8 <= q[0] <= x + w - margin + 1e-8 \
            and y + margin - 1e-8 <= q[1] <= y + h - margin + 1e-8

    def contains_box(self, box):
        return isinstance(box, list) and len(box) == 4 and all(
            type(v) in (int, float) for v in box) and box[2] > 0 and box[3] > 0 \
            and all(self.contains_source(p) for p in corners(box))

    def require_geometry(self, design):
        if not isinstance(design, dict):
            raise ValueError('image_edit_geometry_invalid')
        for box in design.get('markers', []):
            if box is not None and not self.contains_box(box):
                raise ValueError('image_crop_hides_marker')
        for dial in design.get('dials', []):
            if not isinstance(dial, dict) or not self.contains_box(dial.get('crop')):
                raise ValueError('image_crop_hides_dial')
            for p in [*dial.get('rim_points', []), dial.get('needle_pivot')]:
                if p is not None and not self.contains_source(p):
                    raise ValueError('image_crop_hides_dial')

    def report(self):
        return dict(edit=deepcopy(self.value), sha256=self.sha256, extent=self.extent,
                    source_to_view=self.source_to_view, view_to_source=self.view_to_source,
                    scale=self.scale, offset=self.offset, source_size=list(SIZE), view_size=list(SIZE))

    def render(self, blob):
        original = image_rgb(blob)
        image = original.transform(SIZE, Image.Transform.AFFINE, self.view_to_source,
                                   resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0))
        # A transform must not expose pixels outside the selected oriented crop.
        x, y = self.offset
        w, h = self.value['crop'][2:]
        result = Image.new('RGB', SIZE)
        content = [math.ceil(x - 1e-8), math.ceil(y - 1e-8),
                   math.floor(x + w * self.scale + 1e-8), math.floor(y + h * self.scale + 1e-8)]
        result.paste(image.crop(content), content[:2])
        stream = io.BytesIO()
        result.save(stream, format='PNG')
        return stream.getvalue()


class EditStore:
    def __init__(self, directory, reference, atomic):
        self.saved = SavedFile(Path(directory) / 'image-edit.json')
        self.reference, self.atomic = reference, atomic
        self.lock = threading.RLock()
        self.active = None
        try:
            raw = self.saved.read()
            if raw is not None:
                value = strict_json(raw)
                if not isinstance(value, dict) or set(value) != {'version', 'reference_sha256', 'edit'} \
                        or type(value['version']) is not int or value['version'] != 1:
                    raise ValueError('image_edit_invalid')
                self.reference(value['reference_sha256'])
                edit = Edit(value['edit'])
                self.active = dict(version=1, reference_sha256=value['reference_sha256'], edit=edit.value)
        except (ValueError, KeyError, TypeError, UnicodeError, RecursionError):
            self.saved.failed('saved_image_edit_invalid')
        except OSError:
            self.saved.failed('image_edit_storage_unavailable')

    def status(self):
        with self.lock:
            return dict(revision=self.saved.revision, image_edit=deepcopy(self.active), **self.saved.recovery())

    def current(self, reference):
        with self.lock:
            return Edit(self.active['edit'] if self.active and self.active['reference_sha256'] == reference else None)

    def save(self, reference, value, revision, geometry=None):
        self.reference(reference)
        edit = Edit(value)
        if geometry is not None:
            edit.require_geometry(geometry)
        document = dict(version=1, reference_sha256=reference, edit=edit.value)
        raw = json.dumps(document, sort_keys=True, indent=2, allow_nan=False).encode()
        with self.lock:
            if self.saved.revision != revision:
                raise ValueError('image_edit_changed_reload_before_saving')
            if self.active == document:
                return self.status()
            self.saved.replace(raw, self.atomic, 'image_edit_changed_reload_before_saving')
            self.active = document
            return self.status()
