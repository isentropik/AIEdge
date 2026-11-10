"""Bounded photo evidence selection; never changes measurement/gap records."""
import bisect

# Diagnostic photo priority only, NOT a consumption or appliance bound.
LONG_INTERVAL_US = 30_000_000
OLDER_BYTES = 64 * 1024 * 1024


def gap_pairs(db, with_events=False):
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
        # Never combine acceptance from different interpretations/segments.
        columns = {r[1] for r in db.execute('PRAGMA table_info(consumption_records)')}
        segment = 'segment_id' if 'segment_id' in columns else "''"
        states = {}
        for key, event, accepted, state, unbounded in db.execute(f"""
                SELECT {segment},event_id,json_extract(result,'$.observation_accepted'),
                       json_extract(result,'$.state'),json_extract(result,'$.upper_unbounded')
                FROM consumption_records ORDER BY event_id"""):
            prior, last, ambiguous = states.get(key, (None, None, False))
            index = bisect.bisect_left(ids,event)
            if index == len(ids) or ids[index] != event:
                raise ValueError('retention accounting event missing')
            if accepted == 1:
                if prior is not None and index > prior+1:
                    pairs.add((prior,index))
                uncertain = state == 'ambiguous' or unbounded == 1
                if uncertain and not ambiguous and prior is not None:
                    pairs.add((prior,index))
                ambiguous = uncertain
                prior = index
            last = index
            states[key] = (prior,last,ambiguous)
        for prior,last,_ in states.values():
            if prior is not None and last > prior:
                pairs.add((prior,last))
    # Preserve both sides of long intervals even without a recorded exception.
    # Missing/changed clocks also cannot establish continuity.
    for i in range(1, len(rows)):
        a,b = rows[i-1],rows[i]
        if (a[2:4] != b[2:4] or a[3] is None or b[3] is None
                or a[4] is None or b[4] is None or not 0 < b[4]-a[4] < LONG_INTERVAL_US):
            pairs.add((i-1,i))
    ordered = sorted(pairs,reverse=True)
    if with_events:
        return [(rows[a][0],rows[b][0],(rows[a][1],rows[b][1])) for a,b in ordered]
    return [(rows[a][1],rows[b][1]) for a,b in ordered]


def older_keep(db, eligible, pinned, slots, byte_limit=OLDER_BYTES, report=None, evidence=None):
    sizes = dict(db.execute('SELECT sha256,MAX(bytes) FROM frames GROUP BY sha256'))
    kept = set()
    used = 0
    def admit(group):
        nonlocal used
        # Do not spend the bounded evidence pool on an already broken pair.
        if not set(group) <= eligible | pinned:
            return False
        add = set(group) & eligible - pinned - kept
        size = sum(sizes[s] for s in add)
        if len(kept)+len(add) <= slots and used+size <= byte_limit:
            kept.update(add)
            used += size
            return True
        return False
    # Atomic pair selection: never spend the last slot on half a pair.
    evidence = gap_pairs(db, with_events=True) if evidence is None else evidence
    pairs = [p for _,_,p in evidence]
    for pair in pairs:
        admit(pair)
    gap_members = {s for pair in pairs for s in pair}
    # Do not re-admit an evicted pair's half as an arbitrary development photo.
    for image in sorted(eligible - pinned - gap_members):
        admit((image,))
    if report is not None:
        available = eligible | pinned
        retained = kept | pinned
        closed = [p for a,b,p in evidence if a != b]
        pending = [p for a,b,p in evidence if a == b]
        complete = sum(set(p) <= retained for p in closed)
        missing = sum(not set(p) <= available for p in closed)
        report.update(gap_pairs=len(pairs), complete_pairs=complete,
                      missing_endpoint_pairs=missing,
                      budget_excluded_pairs=len(closed)-complete-missing,
                      awaiting_right_endpoint=len(pending),
                      awaiting_right_left_retained=sum(set(p) <= retained for p in pending),
                      selected_older_images=len(kept), selected_older_bytes=used,
                      older_image_limit=slots, older_byte_limit=byte_limit,
                      policy='newest_complete_pairs_first',
                      coverage_complete=complete == len(closed) and not pending)
    return kept
