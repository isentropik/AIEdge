"""Read the coarse gas register from the saved dial faces when an adjacent pair conflicts."""

from functools import lru_cache
from io import BytesIO
from math import isfinite
import hashlib
import numpy as np
from PIL import Image
from observation_support import observed_rows
from reading_bounds import feasible_ranges
from reading_format import validate


def gray(blob):
    with Image.open(BytesIO(blob)) as im:
        if im.size != (640, 480):
            raise ValueError("unexpected capture dimensions")
        return np.asarray(im.convert("L"), dtype=np.float32)


def translation(reference, current, markers):
    """Only accept a common translation supported by distinct printed marks."""
    shifts = []
    boxes = []
    for m in markers:
        x, y, w, h = m["box"]
        if min(w, h) < 12 or max(w, h) > 128 or x < 9 or y < 9 or x + w + 9 > 640 or y + h + 9 > 480:
            return None
        if any(
            x < right and left < x + w and y < bottom and top < y + h
            for left, top, right, bottom in boxes
        ):
            return None
        boxes.append((x, y, x + w, y + h))
        base = reference[y : y + h : 3, x : x + w : 3]
        base = base - base.mean()
        crop = current[y - 9 : y + h + 9, x - 9 : x + w + 9]
        grid = np.lib.stride_tricks.sliding_window_view(crop, (h, w))[:, :, ::3, ::3]
        grid = grid - grid.mean(axis=(2, 3), keepdims=True)
        scores = (grid * base).sum(axis=(2, 3)) / np.maximum(
            1, np.sqrt((grid * grid).sum(axis=(2, 3)) * (base * base).sum())
        )
        j, i = np.unravel_index(np.argmax(scores), scores.shape)
        removed = scores.copy()
        removed[max(0, j - 2) : j + 3, max(0, i - 2) : i + 3] = -1
        if scores[j, i] < 0.90 or scores[j, i] - removed.max() < 0.04 or i in (0, 18) or j in (0, 18):
            return None
        shifts.append([i - 9, j - 9])
    if len(shifts) < 2 or np.max(np.ptp(shifts, axis=0)) > 2:
        return None
    return np.rint(np.median(shifts, axis=0)).astype(int)


_ANGLES = np.deg2rad(np.arange(0, 360, 0.5))


def shaft(diff, center, vertical, horizontal, radii):
    ray = vertical[:, None] * np.cos(_ANGLES) + horizontal[:, None] * np.sin(_ANGLES)
    x, y = center[:, None, None] + np.linspace(*radii, 11)[None, :, None] * ray[:, None, :]
    ix = x.astype(int)
    iy = y.astype(int)
    if ix.min() < 0 or iy.min() < 0 or ix.max() + 1 >= 640 or iy.max() + 1 >= 480:
        return None
    dx = x - ix
    dy = y - iy
    samples = (
        (1 - dx) * (1 - dy) * diff[iy, ix]
        + dx * (1 - dy) * diff[iy, ix + 1]
        + (1 - dx) * dy * diff[iy + 1, ix]
        + dx * dy * diff[iy + 1, ix + 1]
    )
    score = np.quantile(samples, 0.2, axis=0)
    score = np.maximum(0, score - np.quantile(score, 0.2))
    k = int(np.argmax(score))
    offset = (np.arange(len(score)) - k + 360) % 720 - 360
    if score[k] < 30 or score[np.abs(offset) > 24].max() > 0.65 * score[k]:
        return None
    mask = np.abs(offset) <= 14
    weights = np.maximum(0, score[mask] - 0.45 * score[k])
    return float((k + np.average(offset[mask], weights=weights)) % 720 / 72)


def displacement(a, b):
    return (a - b + 5) % 10 - 5


def read_face(diff, item, error):
    mark = item["landmarks"]
    rim = np.asarray(mark["rim_points"], dtype=float)
    if rim.shape != (4, 2) or not np.isfinite(rim).all():
        return None
    top, right, bottom, left = rim
    vals = []
    for center in (rim.mean(axis=0), np.asarray(mark["needle_pivot"], dtype=float)):
        for radii in ((0.75, 0.88), (0.82, 0.94)):
            pos = shaft(diff, center, (top - bottom) / 2, (right - left) / 2, radii)
            if pos is None:
                return None
            vals.append(pos if item["direction"] == "cw" else -pos % 10)
    unwrapped = [vals[0] + displacement(v, vals[0]) for v in vals]
    lo, hi = min(unwrapped), max(unwrapped)
    if hi - lo > error:
        return None
    return ((lo + hi) / 2) % 10, (hi - lo) / 2


def hundreds(profile, ref, img, doc, positions, indices):
    """Intersect the envelope of both photo fits with every unaffected dial."""
    dials = doc["dials"]
    scales = [row["value_per_revolution"] for row in dials]
    if (
        len(dials) < 4
        or scales[-3:-1] != [10000, 1000]
        or not 0 < scales[-1] < 100
        or indices != [d["index"] for d in dials[-3:-1]]
    ):
        return None
    shift = translation(ref, img, profile["markers"])
    if shift is None:
        return None
    diff = ref - np.roll(img, (-shift[1], -shift[0]), axis=(0, 1))
    fitted = list(positions)
    errors = [float(d["position_error"]) for d in dials]
    confirmed = []
    details = []
    for j in (len(dials) - 3, len(dials) - 2):
        index = dials[j]["index"]
        item = profile["dials"][index]
        if (
            item.get("model") != "main"
            or item.get("direction") not in ("cw", "ccw")
            or not 0 < errors[j] <= 0.1
        ):
            return None
        fit = read_face(diff, item, errors[j])
        if fit is None:
            return None
        angle, spread = fit
        confirmed.append(abs(displacement(angle, positions[j])) <= 2 * errors[j] + spread)
        fitted[j] = angle
        errors[j] += spread
        details.append(dict(index=index, model=positions[j], photo=angle, half_spread=spread))
    # Require independent agreement on the neighboring lower dial. Limit this
    # recovery to the demonstrated opposite-sides-of-zero error on its neighbor.
    if confirmed != [False, True] or positions[-3] - fitted[-3] < 9:
        return None
    result = feasible_ranges(scales, fitted, errors)
    if result["state"] != "bounded" or result.get("wraps_register"):
        return None
    values = {int(edge // 100) * 100 for band in result["intervals"] for edge in band}
    if len(values) != 1:
        return None
    return dict(register_ft3=values.pop(), resolution_ft3=100, fits=details)


class PhotoRegister:
    def __init__(self, store, setup):
        self.store = store
        self.setup = setup
        self.reference = lru_cache(maxsize=1)(lambda digest: gray(setup.reference(digest)))

    def check(self, snap, inf):
        raw = snap.get("_raw_meter_reading") or {}
        c = snap.get("consumption") or {}
        doc = snap.get("format") or {}
        src = c.get("event_observation") or {}
        frame = snap.get("latest") or {}
        if (
            doc.get("unit") != "ft3"
            or raw.get("reason") != "dial_bounds_disagree"
            or raw.get("state") != "inconsistent"
            or c.get("reason") != "consumption_positions_contradict_bounds"
            or c.get("observation_accepted") is not False
            or not src
            or inf.get("event_observation") != src
            or inf.get("state") != "estimated"
            or c.get("segment_id") != snap.get("_publication_segment_id")
            or not c.get("segment_id")
        ):
            return None
        try:
            sha = src["source_sha256"]
            eid = src["event_id"]
            support = c["observation_support"]
            complete = [True] * len(doc["dials"])
            if (
                not isinstance(support, dict)
                or support.get("schema_version") != 1
                or support.get("document_observed") != complete
                or support.get("source_sha256") != sha
                or support.get("pipeline_id") != doc["pipeline_id"]
                or observed_rows(inf) != complete
                or any(
                    row.get("state") != "estimated" or row.get("source_sha256", sha) != sha
                    for row in inf["dial_positions"]
                )
                or type(src.get("event_id")) is not int
                or type(src.get("monotonic_us")) is not int
                or not isinstance(src.get("camera"), str)
                or not src["camera"]
                or not all(
                    x == sha
                    for x in (
                        c["source_sha256"],
                        inf["source_sha256"],
                        raw["source_sha256"],
                        frame["sha256"],
                    )
                )
                or not (eid == snap["_timing_event_id"] == c["event_id"])
                or frame["captured_at"] != src["captured_at"]
                or inf["pipeline_id"] != doc["pipeline_id"]
                or not (validate(doc)[1] == src["format_id"] == raw["format_id"] == c["format_id"])
                or src["context_id"] != c["observation_context"]
                or not src["clock_id"]
            ):
                return None
            setup = self.setup.status()
            profile = setup["calibration"]
            if setup["revision"] != inf["profile"] or len(profile["dials"]) != len(doc["dials"]):
                return None
            positions = [inf["dial_positions"][d["index"]]["position"] for d in doc["dials"]]
            if not all(type(v) in (int, float) and isfinite(v) and 0 <= v < 10 for v in positions):
                return None
            blob = self.store.image(sha)
            if hashlib.sha256(blob).hexdigest() != sha:
                return None
            found = hundreds(
                profile,
                self.reference(profile["reference_sha256"]),
                gray(blob),
                doc,
                positions,
                raw["consistency"]["dial_indices"],
            )
            if found:
                return dict(found, source=dict(src), reference_sha256=profile["reference_sha256"])
        except (OSError, ValueError, TypeError, KeyError, IndexError, ArithmeticError):
            return None
