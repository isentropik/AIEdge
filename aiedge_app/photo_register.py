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
    samples = radial_samples(diff, center, ray, np.linspace(*radii, 11))
    if samples is None:
        return None
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


def radial_samples(image, center, rays, radii):
    x, y = center[:, None, None] + np.asarray(radii)[None, :, None] * rays[:, None, :]
    if x.min() < 0 or y.min() < 0 or x.max() >= image.shape[1]-1 or y.max() >= image.shape[0]-1:
        return None
    ix, iy = x.astype(int), y.astype(int)
    dx, dy = x-ix, y-iy
    return ((1-dx)*(1-dy)*image[iy, ix] + dx*(1-dy)*image[iy, ix+1]
            + (1-dx)*dy*image[iy+1, ix] + dx*dy*image[iy+1, ix+1])


def dark_stroke(angles, intensity, widths, change=None, *, local_contrast=False, edges=False):
    """Require one isolated ink stroke of the expected angular width."""
    threshold = 75
    if local_contrast:
        ink, paper = np.quantile(intensity, (.06, .80))
        if paper - ink < 45:
            return None
        threshold = (ink + paper) / 2
    dark = np.flatnonzero(intensity < threshold)
    strokes = []
    for run in np.split(dark, np.flatnonzero(np.diff(dark) > 1) + 1):
        if not len(run) or run[0] == 0 or run[-1] == len(angles)-1:
            continue
        width = angles[run[-1]] - angles[run[0]]
        if widths[0] <= width <= widths[1] and (change is None or change[run].mean() >= 40):
            strokes.append((float(angles[run[0]]), float(angles[run[-1]]))
                           if edges else float(angles[run].mean()))
    return strokes[0] if len(strokes) == 1 else None


def indexed_tip(image, diff, item, error):
    """Measure the tip relative to a printed division visible beyond the pointer."""
    mark = item["landmarks"]
    rim = np.asarray(mark["rim_points"], dtype=float)
    if rim.shape != (4, 2) or not np.isfinite(rim).all():
        return None
    top, right, bottom, left = rim
    vertical, horizontal = (top-bottom)/2, (right-left)/2
    sign = 1 if item["direction"] == "cw" else -1

    def rays(angles):
        radians = angles * sign * np.pi / 5
        return vertical[:, None]*np.cos(radians) + horizontal[:, None]*np.sin(radians)

    results = []
    for center in (rim.mean(axis=0), np.asarray(mark["needle_pivot"])):
        seed = shaft(diff, center, vertical, horizontal, (.82, .94))
        if seed is None:
            return None
        angles = sign*seed + np.arange(-.50, .501, .005)
        radii = (.88, .90, .92, .94)
        ink = radial_samples(image, center, rays(angles), radii)
        change = radial_samples(diff, center, rays(angles), radii)
        if ink is None or change is None:
            return None
        tips = [dark_stroke(angles, row, (.10, .36), changed) for row, changed in zip(ink, change)]
        if None in tips or np.ptp(tips) > error:
            return None
        division = round(float(np.mean(tips)))
        ticks = division + np.arange(-.23, .231, .005)
        outer = radial_samples(image, center, rays(ticks), (1.06, 1.07, 1.08))
        if outer is None:
            return None
        marks = [dark_stroke(ticks, row, (.02, .16)) for row in outer]
        if None in marks or np.ptp(marks) > error:
            return None
        results.extend(division + tip - tick for tip in tips for tick in marks)
    values = [results[0]+displacement(v, results[0]) for v in results]
    if np.ptp(values) > error:
        return None
    return ((max(values)+min(values))/2) % 10, float(np.ptp(values))/2


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


def bracketed_tip(image, diff, item, guess, error, *, covered_division=False, outer_tip=False,
                  footprint=False):
    """Read the moving tip against the two printed divisions on either side."""
    mark = item["landmarks"]
    rim = np.asarray(mark["rim_points"], dtype=float)
    if rim.shape != (4, 2) or not np.isfinite(rim).all():
        return None
    top, right, bottom, left = rim
    sign = 1 if item["direction"] == "cw" else -1

    def rays(angles):
        radians = angles * sign * np.pi / 5
        return ((top-bottom)[:, None]*np.cos(radians) + (right-left)[:, None]*np.sin(radians))/2

    def strokes(center, angles, radii, widths, moving):
        ray = rays(angles)
        ink = radial_samples(image, center, ray, radii)
        change = radial_samples(diff, center, ray, radii) if moving or outer_tip else None
        if ink is None or (moving or outer_tip) and change is None:
            return []
        readings = []
        for i, row in enumerate(ink):
            value = dark_stroke(angles, row, widths, change[i] if moving else None,
                                local_contrast=outer_tip, edges=footprint and moving)
            if value is None:
                continue
            if outer_tip and not moving:
                # A moving tip protruding past the rim cannot serve as a printed tick.
                reference = dark_stroke(angles, row+change[i], widths, local_contrast=True)
                if reference is None or abs(reference-value) > error:
                    continue
            readings.append(value)
        return readings

    # The digits can overlap the inner shaft. Independently measure the outer
    # tip and the exposed print beyond the rim when the inner scan is unusable.
    tip_radii = (.90, .915, .93, .945, .96) if outer_tip else (.84, .86, .88, .90, .92)
    mark_radii = (1.04, 1.06, 1.08, 1.10, 1.12) if outer_tip else (1.02, 1.04, 1.06, 1.08)
    values = []
    edges = []
    for center in (rim.mean(axis=0), np.asarray(mark["needle_pivot"], dtype=float)):
        observed_tip = strokes(center, guess+np.arange(-.50, .501, .005),
                               tip_radii, (.10, .36), True)
        tips = [sum(pair)/2 for pair in observed_tip] if footprint else observed_tip
        if len(tips) < 3 or np.ptp(tips) > error:
            return None
        middle = round(float(np.mean(tips)))
        if covered_division and max(abs(tip-middle) for tip in tips) > .25:
            return None
        left_tick = middle-1 if covered_division else int(np.floor(np.mean(tips)))
        span = 2 if covered_division else 1
        marks = []
        for tick in (left_tick, left_tick+span):
            observed = strokes(center, tick+np.arange(-.20, .201, .005),
                               mark_radii, (.02, .16), False)
            if len(observed) < 2 or np.ptp(observed) > error:
                return None
            marks.append((min(observed), max(observed)))
        for lo in marks[0]:
            for hi in marks[1]:
                if abs((hi-lo)-span) > error or not lo <= min(tips) <= max(tips) <= hi:
                    return None
                values.extend(left_tick+span*(tip-lo)/(hi-lo) for tip in tips)
                if footprint:
                    # Both centers must place ink over the obscured division.
                    midpoint = (lo+hi)/2
                    if not any(left <= midpoint <= right for left, right in observed_tip):
                        return None
                    edges.extend(left_tick+span*(edge-lo)/(hi-lo) for pair in observed_tip for edge in pair)
    if np.ptp(values) > error:
        return None
    if footprint:
        # The tip covers the central index. Its visible ink edges, projected
        # between the two exposed indices, bound the indication on this face.
        # Two centers can put the axis on opposite sides of a graduation
        # even while agreeing on which graduation the ink covers.
        side_resolved = max(values) < guess or min(values) > guess
        return ((min(edges)+max(edges))/2) % 10, float(np.ptp(edges))/2, side_resolved
    return ((min(values)+max(values))/2) % 10, float(np.ptp(values))/2


def covered_upper_tip(image, diff, item, error):
    """Accept exactly one moving tip bracketed by the same print in both photos."""
    found = None
    for division in range(10):
        fit = bracketed_tip(image, diff, item, division, error, covered_division=True,
                            outer_tip=True, footprint=True)
        if fit is not None:
            if found is not None:
                return None
            found = fit
    return found[:2] if found is not None and found[2] else None


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
    aligned = np.roll(img, (-shift[1], -shift[0]), axis=(0, 1))
    diff = ref - aligned
    fitted = list(positions)
    errors = [float(d["position_error"]) for d in dials]
    confirmed = []
    details = []
    indexed = False
    covered = False
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
        if fit is None and j == len(dials)-3:
            fit = covered_upper_tip(aligned, diff, item, errors[j])
        if j == len(dials)-2:
            indexed_fit = indexed_tip(aligned, diff, item, errors[j])
            if indexed_fit is None:
                indexed_fit = bracketed_tip(aligned, diff, item, positions[j], errors[j])
            if indexed_fit is None:
                # A pointer covering a printed mark leaves its two neighbors visible.
                indexed_fit = bracketed_tip(aligned, diff, item, positions[j], errors[j], covered_division=True)
                covered = indexed_fit is not None
            if indexed_fit is None:
                indexed_fit = bracketed_tip(aligned, diff, item, positions[j], errors[j], outer_tip=True)
            if indexed_fit is not None:
                fit = indexed_fit
                indexed = True
        if fit is None:
            return None
        angle, spread = fit
        confirmed.append(abs(displacement(angle, positions[j])) <= 2 * errors[j] + spread)
        fitted[j] = angle
        errors[j] += spread
        details.append(dict(index=index, model=positions[j], photo=angle, half_spread=spread))
    # The lower dial must corroborate its model. A same-side upper-dial
    # correction also requires an independently visible printed index.
    wrapped = confirmed == [False, True] and positions[-3] - fitted[-3] >= 9
    correction = abs(displacement(fitted[-3], positions[-3]))
    # Small offsets can make adjacent model bands disjoint at a carry. A
    # visible index and two corroborated face measurements still establish a
    # register range. Keep each fit's measured spread in that intersection.
    corroborated = all(abs(displacement(f["photo"], f["model"])) <=
                       dials[j]["position_error"] + f["half_spread"]
                       for j, f in zip((-3, -2), details))
    if not wrapped and not (indexed and confirmed[-1] and correction <= 1
                            and (covered or corroborated or correction >= dials[-3]["position_error"])):
        return None
    result = feasible_ranges(scales, fitted, errors)
    if result["state"] != "bounded" or result.get("wraps_register"):
        return None
    values = {int(edge // 100) * 100 for band in result["intervals"] for edge in band}
    if len(values) != 1 and not indexed:
        return None
    bands = result["intervals"]
    proof = dict(fits=details, bands_ft3=[[str(lo), str(hi)] for lo, hi in bands])
    if indexed:
        if bands[-1][1] - bands[0][0] >= 100:
            return None
        middle = float((bands[0][0]+bands[-1][1])/2)
        phase = fitted[-2]*scales[-2]/10
        proof["photo_center_ft3"] = phase + round((middle-phase)/scales[-2])*scales[-2]
    if len(values) == 1:
        proof.update(register_ft3=values.pop(), resolution_ft3=100)
    return proof


class PhotoRegister:
    def __init__(self, store, setup):
        self.store = store
        self.setup = setup
        self.reference = lru_cache(maxsize=1)(lambda digest: gray(setup.reference(digest)))

    def fit_original(self, doc, inf, blob, indices):
        """Measure both conflicting pointers on the same calibrated original."""
        profile_state = self.setup.status()
        profile = profile_state["calibration"]
        if (doc.get("unit") != "ft3" or profile_state["revision"] != inf.get("profile")
                or len(profile["dials"]) != len(doc["dials"])
                or hashlib.sha256(blob).hexdigest() != inf["source_sha256"]):
            return None
        positions = [inf["dial_positions"][d["index"]]["position"] for d in doc["dials"]]
        if not all(type(v) in (int, float) and isfinite(v) and 0 <= v < 10 for v in positions):
            return None
        reference = profile["reference_sha256"]
        found = hundreds(profile, self.reference(reference), gray(blob), doc, positions, indices)
        if found:
            return dict(found, reference_sha256=reference)

    def check(self, snap, inf, *, image=None):
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
            try:
                blob = self.store.image(sha) if image is None else image
            except FileNotFoundError:
                from original_dials import saved
                with self.store.connect() as db:
                    evidence = saved(db, sha, src["format_id"], doc["pipeline_id"])
                positions = [inf["dial_positions"][d["index"]]["position"] for d in doc["dials"]]
                if (not evidence or not evidence.get("fits") or evidence["positions"] != positions
                        or evidence["calibration"] != inf.get("profile")
                        or self.setup.status()["revision"] != evidence["calibration"]):
                    return None
                keys = ("bands_ft3", "fits", "reference_sha256", "photo_center_ft3", "register_ft3", "resolution_ft3")
                found = {key: evidence[key] for key in keys if key in evidence}
            else:
                found = self.fit_original(doc, inf, blob, raw["consistency"]["dial_indices"])
            if found:
                return dict(found, source=dict(src))
        except (OSError, ValueError, TypeError, KeyError, IndexError, ArithmeticError):
            return None
