"""Read capture-bound native accounting evidence from the app's own SQLite ledger."""
import json
from decimal import Decimal


def daily_records(db, first_event, through_event, segment_id):
    """Stream accepted measurements over an inclusive event range, in capture order.

    Rejected observations remain in the ledger. No image payloads are required.
    Conflicting identities invalidate the calculation instead of choosing a segment.
    """
    query = """
        WITH RECURSIVE lineage(segment_id, last_event) AS (
            SELECT ?, ?
            UNION
            SELECT l.prior_segment_id, min(child.last_event, l.first_event - 1) FROM consumption_segment_links AS l
            JOIN lineage AS child ON child.segment_id = l.segment_id
            WHERE l.first_event > ?
        )
        SELECT e.event_id, e.camera, f.captured_at, f.sha256,
               c.clock_id, c.monotonic_us, r.segment_id, r.result
        FROM capture_events AS e
        JOIN frames AS f USING (camera, frame_id)
        LEFT JOIN capture_clocks AS c USING (camera, frame_id)
        JOIN consumption_records AS r ON r.event_id = e.event_id
        JOIN lineage ON lineage.segment_id = r.segment_id AND e.event_id <= lineage.last_event
        WHERE r.event_id BETWEEN ? AND ?
        ORDER BY e.event_id, r.segment_id
    """
    # Fetch short pages so JSON parsing and calendar arithmetic hold no read lock.
    # The immutable lineage starts at the specific publication segment on every page.
    for start in range(first_event, through_event + 1, 64):
        stop = min(start + 63, through_event)
        rows = db.execute(query, (segment_id, through_event, start, start, stop)).fetchall()
        yield from bound_rows(rows)


def bound_rows(rows):
    previous = None
    for event, camera, stamp, digest, clock, tick, segment, encoded in rows:
        record = json.loads(encoded, parse_float=Decimal)
        if record.get("observation_accepted") is not True:
            continue
        if event == previous:
            raise ValueError("multiple accepted interpretations of one capture")
        previous = event
        binding = record.get("event_observation") or {}
        expected = {
            "event_id": event, "camera": camera, "captured_at": stamp,
            "source_sha256": digest, "clock_id": clock, "monotonic_us": tick,
            "context_id": record.get("observation_context"),
            "format_id": record.get("format_id"),
        }
        if (not all(expected[k] for k in ("context_id", "format_id", "clock_id"))
                or type(tick) is not int or tick < 0
                or not isinstance(digest, str) or len(digest) != 64
                or any(ch not in "0123456789abcdef" for ch in digest)
                or any(binding.get(k) != v or type(binding.get(k)) is not type(v)
                       for k, v in expected.items())
                or record.get("segment_id") != segment or record.get("event_id") != event
                or record.get("through_captured_at") != stamp
                or record.get("observation_current_through_us") != tick
                or record.get("source_sha256") != digest):
            raise ValueError("daily measurement does not match its capture")
        yield record



