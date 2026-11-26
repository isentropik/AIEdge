"""Absolute meter estimate from a photo anchor and contiguous saved fine-dial observations."""

from datetime import datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from hashlib import sha256

from capture_clock import interval
from daily_constraints import WorkLimit, bands, number, supported
from dial_travel import advance_band, phases
from nominal_motion import PAGE, step
from optical_daily import endpoint

METHOD = "photo_anchored_fine_dial"
ASSUMPTION = (
    "Uses the feasible band nearest the measured photo center when available. "
    "Without a measured center, starts in the middle feasible band, lower on a tie. "
    "After a break it uses the smallest reachable forward reading. "
    "Follows the smallest supported forward movement. Re-anchors after a break require "
    "an independent absolute reading. Consumption across gaps is unknown."
)


def meter_rate(document):
    """Physical flow constraint from the configured meter reading format."""
    return number(document["maximum_rate_per_second"])


def measurement(track, source):
    lo, hi = map(number, track["outer"])
    return {
        "value_ft3": track["level"],
        "measured_at": source["captured_at"],
        "event_id": source["event_id"],
        "source_sha256": source["source_sha256"],
        "method": METHOD,
        "status": "estimated",
        "lower_ft3": str(lo.quantize(Decimal(".1"), rounding=ROUND_FLOOR)),
        "upper_ft3": str(hi.quantize(Decimal(".1"), rounding=ROUND_CEILING)),
        "anchor_event_id": track["anchor"]["event_id"],
        "anchor_measured_at": track["anchor"]["captured_at"],
        "anchor_source_sha256": track["anchor"]["source_sha256"],
        "assumption": ASSUMPTION,
    }


def start(source, options, floor, *, previous=None, limit=None, photo_center=None):
    # Select an actual feasible band. The midpoint of the entire envelope can be between turns.
    if not options:
        return None
    if photo_center is None:
        i = (len(options) - 1) // 2 if previous is None else 0
        candidates = options[i:]
    else:
        candidates = [(max(lo, floor), min(hi, previous+limit) if previous is not None else hi)
                      for lo, hi in options]
        candidates = [(lo, hi) for lo, hi in candidates if lo <= hi]
        candidates.sort(key=lambda band: abs((band[0]+band[1])/2 - photo_center))
    for lo, hi in candidates:
        if hi < floor:
            continue
        level = max(floor, (lo + hi) / 2 if previous is None or photo_center is not None else lo)
        if previous is not None and level > previous + limit:
            return None
        track = {
            "source": source,
            "anchor": source,
            "band": [str(lo), str(hi)],
            "level": str(level),
            "outer": [str(options[0][0]), str(options[-1][1])],
        }
        track["display"] = measurement(track, source)
        return track


def advance(track, source, phase, turn, limit, options):
    """Propagate all possible turns for bounds, and the chosen turn separately for display."""
    old = tuple(map(number, track["band"]))
    outer = advance_band(tuple(map(number, track["outer"])), phase, turn, limit)
    chosen = step(old, phase, turn, limit)
    if outer is None or chosen is None or chosen[0] - old[1] >= turn / 2:
        return None
    possible = supported(options, [outer], 0, 0) if options else [outer]
    if not possible:
        return None
    outer = (possible[0][0], possible[-1][1])
    last = number(track["level"])
    # Bounds alone cannot cause the nominal to jump to another five-foot alternative.
    choices = supported(possible, [chosen], 0, 0)
    choices = supported(choices, [(last, last)], 0, limit)
    result = dict(
        track, source=source, outer=list(map(str, outer)), band=list(map(str, chosen))
    )
    if choices:
        lo, hi = choices[0]
        result.update(level=str(lo), band=[str(lo), str(hi)], needs_confirmation=False)
        result["display"] = measurement(result, source)
    else:
        result["needs_confirmation"] = True
    return result


def elapsed_seconds(source, last_time, last_clock, last_tick):
    wall = (
        datetime.fromisoformat(source["captured_at"])
        - datetime.fromisoformat(last_time)
    ).total_seconds()
    if source["clock_id"] == last_clock:
        return min(wall, (source["monotonic_us"] - last_tick) / 1000000)
    return wall


def matches_measurement(state, source):
    return (state["event_id"], state["source_sha256"], state["measured_at"]) == (
        source["event_id"],
        source["source_sha256"],
        source["captured_at"],
    )


def observed_bands(snapshot, source):
    """Intersect the full current photo with the independently constrained meter range."""
    raw = snapshot.get("_raw_meter_reading") or {}
    consumption = snapshot["consumption"]
    document = snapshot["format"]
    support = consumption.get("observation_support") or {}
    if (
        raw.get("state") != "ambiguous"
        or raw.get("source_sha256") != source["source_sha256"]
        or raw.get("format_id") != source["format_id"]
        or consumption.get("observation_accepted") is not True
        or type(support.get("schema_version")) is not int or support["schema_version"] != 1
        or support.get("partial") is not False
        or support.get("pipeline_id") != document["pipeline_id"]
        or support.get("source_sha256") != source["source_sha256"]
    ):
        return None
    for key in ("reader_observed", "document_observed"):
        mask = support.get(key)
        if not isinstance(mask, list) or len(mask) != len(document["dials"]) or not all(v is True for v in mask):
            return None
    try:
        modulus = number(document["dials"][0]["value_per_revolution"])
        measured = bands({"absolute": dict(raw, provenance="single_image")}, modulus)
        current = bands(consumption, modulus)
        if measured and current:
            return supported(measured, current, 0, 0)
    except (ArithmeticError, KeyError, TypeError, ValueError, WorkLimit):
        return None


def update(track, store, snapshot, source, options, floor, photo_center=None, *, gap_options=None, rate=None):
    """Use bounded indexed reads; a cursor or display date never substitutes for a meter event."""
    if not track:
        return start(source, options, floor, photo_center=photo_center)
    old = track["source"]
    if (
        any(old[k] != source[k] for k in ("camera", "format_id"))
        or source["event_id"] <= old["event_id"]
        or datetime.fromisoformat(source["captured_at"])
        <= datetime.fromisoformat(old["captured_at"])
    ):
        return track
    doc = snapshot["format"]
    turn = number(doc["dials"][-1]["value_per_revolution"])
    rate = meter_rate(doc) if rate is None else rate
    first = old["event_id"] + 1
    stop = min(source["event_id"], first + PAGE - 1)
    with store.connect() as db:
        samples = phases(db, old["event_id"], stop, doc, source, same_clock=False)
        predecessor = samples.get(old["event_id"])
        if predecessor is None and gap_options:
            predecessor = phases(db, old["event_id"], old["event_id"], doc, old).get(old["event_id"])
        if not predecessor or predecessor[0] != old:
            return track
        breaks = {
            r[0] + 1
            for r in db.execute(
                "SELECT after_event_id FROM capture_failure_boundaries WHERE after_event_id BETWEEN ? AND ?",
                (first - 1, stop - 1),
            )
        }
        breaks.update(
            r[0]
            for r in db.execute(
                "SELECT first_event FROM consumption_segment_links WHERE first_event BETWEEN ? AND ?",
                (first, stop),
            )
        )
        head = (
            samples.get(source["event_id"])
            if stop == source["event_id"]
            else phases(db, source["event_id"], source["event_id"], doc, source).get(
                source["event_id"]
            )
        )
        if head is None and gap_options:
            head = phases(db, source["event_id"], source["event_id"], doc, source).get(source["event_id"])
        if not head or head[0] != source:
            return track
        # A worker may have saved a final JPEG without a usable fine-dial
        # observation before shutdown. That hole can precede the recorded break.
        # The new full photo establishes position only; never infer motion over it.
        confirmed_break = old["context_id"] != source["context_id"] or bool(breaks)
        if gap_options and not confirmed_break and stop < source["event_id"]:
            confirmed_break = bool(db.execute(
                "SELECT 1 FROM capture_failure_boundaries WHERE after_event_id >= ? AND after_event_id < ? "
                "UNION ALL SELECT 1 FROM consumption_segment_links WHERE first_event > ? AND first_event <= ? LIMIT 1",
                (stop, source["event_id"], stop, source["event_id"]),
            ).fetchone())
    # When a real link is missing, only an independent, current absolute measurement can re-anchor.
    # This changes meter position, never the consumption ledger or the existing daily checkpoint.
    for eid in range(first, stop + 1):
        row = samples.get(eid)
        if not row:
            break
        current, phase = row
        prev = track["source"]
        timing = interval(prev, current)
        if (
            eid in breaks
            or prev["context_id"] != current["context_id"]
            or timing["state"] != "continuous"
            or timing["elapsed_seconds"] >= 660
        ):
            options = options or gap_options
            break
        limit = rate * number(current["monotonic_us"] - prev["monotonic_us"]) / 1000000
        absolute = options if eid == source["event_id"] else None
        updated = advance(track, current, phase, turn, limit, absolute)
        if updated is None:
            # A conflicting absolute observation cannot declare an extra turn.
            if absolute and advance(track, current, phase, turn, limit, None):
                return dict(track, needs_confirmation=True)
            break
        if track.get("needs_confirmation") and not absolute:
            updated.update(display=track["display"], needs_confirmation=True)
        track = updated
    else:
        return track
    if confirmed_break:
        options = options or gap_options
    if options:
        # A new absolute observation may fix position on the far side of a discontinuity.
        # The maximum rate limits which forward re-anchors are reachable across the elapsed time.
        last = track["source"]
        elapsed = elapsed_seconds(
            source, last["captured_at"], last["clock_id"], last["monotonic_us"]
        )
        if elapsed > 0:
            reachable = supported(
                options, [tuple(map(number, track["outer"]))], 0, rate * number(elapsed)
            )
            previous = number(track["display"]["value_ft3"])
            anchor = start(
                source,
                reachable,
                max(floor, previous),
                previous=previous,
                limit=rate * number(elapsed),
                photo_center=photo_center,
            )
            if anchor:
                return anchor
    return track


def project(prior, record, reason, snapshot, obs, daily, now, max_age, originals=None):
    track = (prior or {}).get("absolute_motion")
    proof = snapshot.get("_photo_register")
    store = getattr(daily, "store", None)
    if store is None or (not track and not (proof or {}).get("bands_ft3") and originals is None):
        return track, False
    src = endpoint(snapshot, obs, True, now, max_age)
    if (
        not src
        or record["format_id"] != src["format_id"]
        or sha256(src["camera"].encode()).hexdigest() != record["source_identity"]
    ):
        return track, False
    if obs and any(
        obs.get(k) != src.get(k)
        for k in ("event_id", "captured_at", "source_sha256", "format_id")
    ):
        return track, False
    doc = snapshot["format"]
    rate = meter_rate(doc)
    state = record.get("state") or {}
    legacy = (prior or {}).get("photo_register") or {}
    floor = number(legacy.get("value_ft3", 0))
    options = None
    photo_center = None
    gap_only = False
    if proof and proof.get("source") == src and proof.get("bands_ft3"):
        options = [tuple(map(number, b)) for b in proof["bands_ft3"]]
        if "photo_center_ft3" in proof:
            photo_center = number(proof["photo_center_ft3"])
    elif track and obs and reason in ("no_continuous_candidate", "whole_turn_unconfirmed"):
        options = observed_bands(snapshot, src)
        gap_only = True
    if options:
        if state:
            # An independent anchor must be reachable from the last accepted register reading.
            seconds = elapsed_seconds(
                src, state["measured_at"], record["clock_id"], record["tick"]
            )
            if seconds <= 0 or src["event_id"] <= state["event_id"]:
                return track, False
            options = supported(
                options,
                [tuple(map(number, b)) for b in state["bands_ft3"]],
                0,
                rate * number(seconds),
            )
            if not options:
                return track, False
            floor = max(floor, number(state["value_ft3"]))
        if legacy and not track:
            if src["event_id"] < legacy["event_id"]:
                return None, False
            seconds = elapsed_seconds(
                src, legacy["measured_at"], legacy["clock_id"], legacy["monotonic_us"]
            )
            if src["event_id"] == legacy["event_id"]:
                if (
                    not matches_measurement(legacy, src)
                    or src["clock_id"] != legacy["clock_id"]
                    or src["monotonic_us"] != legacy["monotonic_us"]
                ):
                    return None, False
            elif seconds <= 0:
                return None, False
            options = supported(
                options,
                [(floor, number(legacy["upper_exclusive_ft3"]))],
                0,
                number(seconds) * rate,
            )
    elif track and state and not reason and matches_measurement(state, src):
        options = [tuple(map(number, b)) for b in state["bands_ft3"]]
    before = track
    if track or options:
        track = update(track, store, snapshot, src, None if gap_only else options, floor,
                       photo_center, gap_options=options if gap_only else None, rate=rate)
    # Finish ordinary bounded replay first. Look for an independent original
    # only when the saved register has stalled on an observed event.
    consumption = snapshot.get('consumption') or {}
    support = consumption.get('observation_support') or {}
    waiting_for_anchor = consumption.get('reason') == 'consumption_partial_requires_full_anchor'
    if (originals is not None and obs and isinstance(support.get('partial'), bool)
            and (not track or track['source'] != src and before
                 and (waiting_for_anchor or track['source'] == before['source']))):
        track = originals.recover(track, record, legacy, snapshot, src, rate=rate)
    if not track:
        return None, False
    if doc.get('pipeline_id') and len(doc['dials']) > 1:
        from register_replay import refine
        track = refine(store, doc, track, rate, originals)
    latest = track["display"]
    current = (
        track["source"] == src
        and not track.get("needs_confirmation")
        and matches_measurement(latest, src)
    )
    return track, current
