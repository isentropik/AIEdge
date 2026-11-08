"""Bounded photo evidence selection; never changes measurement/gap records."""
import bisect

# Diagnostic photo priority only, NOT a consumption or appliance bound.
LONG_INTERVAL_US = 30_000_000
OLDER_BYTES = 64 * 1024 * 1024


def gap_pairs(db):
    rows = db.execute("""SELECT e.event_id,f.sha256,e.camera,c.clock_id,c.monotonic_us
        FROM capture_events e JOIN frames f USING(camera,frame_id)
        LEFT JOIN capture_clocks c USING(camera,frame_id) ORDER BY e.event_id""").fetchall()
    ids = [r[0] for r in rows]
    pairs = set()
    def boundary(after):
        i = bisect.bisect_right(ids, after)
        if i:
            pairs.add((i-1, i if i < len(rows) else i-1))
    for after, in db.execute('SELECT after_event_id FROM capture_failure_boundaries'):
        boundary(after)
    for after, in db.execute("""SELECT a.after_event_id FROM continuous_capture_attempts a
        LEFT JOIN continuous_capture_outcomes o USING(attempt_id)
        WHERE o.outcome IS NULL OR o.outcome!='committed'"""):
        boundary(after)
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'consumption_segment_links' in tables:
        for first, in db.execute('SELECT first_event FROM consumption_segment_links'):
            boundary(first-1)
    if 'consumption_records' in tables:
        prior = None
        last = None
        for event, accepted in db.execute("""SELECT event_id,
                MAX(COALESCE(json_extract(result,'$.observation_accepted'),0))
                FROM consumption_records GROUP BY event_id ORDER BY event_id"""):
            index = bisect.bisect_left(ids,event)
            if index == len(ids) or ids[index] != event:
                raise ValueError('retention accounting event missing')
            if accepted == 1:
                if prior is not None and index > prior+1:
                    pairs.add((prior,index))
                prior = index
            last = index
        if prior is not None and last > prior:
            pairs.add((prior,last))
    # Preserve both sides of long intervals even without a recorded exception.
    # Missing/changed clocks also cannot establish continuity.
    for i in range(1, len(rows)):
        a,b = rows[i-1],rows[i]
        if (a[2:4] != b[2:4] or a[3] is None or b[3] is None
                or a[4] is None or b[4] is None or not 0 < b[4]-a[4] < LONG_INTERVAL_US):
            pairs.add((i-1,i))
    return [(rows[a][1],rows[b][1]) for a,b in sorted(pairs,reverse=True)]


def older_keep(db, eligible, pinned, slots, byte_limit=OLDER_BYTES):
    sizes = dict(db.execute('SELECT sha256,MAX(bytes) FROM frames GROUP BY sha256'))
    kept = set()
    used = 0
    def admit(group):
        nonlocal used
        add = set(group) & eligible - pinned - kept
        size = sum(sizes[s] for s in add)
        if len(kept)+len(add) <= slots and used+size <= byte_limit:
            kept.update(add)
            used += size
    # Atomic pair selection: never spend the last slot on half a pair.
    pairs = gap_pairs(db)
    for pair in pairs:
        admit(pair)
    gap_members = {s for pair in pairs for s in pair}
    # Do not re-admit an evicted pair's half as an arbitrary development photo.
    for image in sorted(eligible - pinned - gap_members):
        admit((image,))
    return kept
