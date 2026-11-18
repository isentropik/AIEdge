"""Bounded comparisons for ambiguous intervals in the saved resumed-usage ledger."""
import bisect
import hashlib
import json
from pathlib import Path

from daily_constraints import number
from daily_empirical import evidence, interval_edges

REVIEW_FILE = 'reviewed-resumed-movements.json'


def gap_edges(db, rows, policy, budget):
    edges = interval_edges(db, rows, policy, budget)
    sources = [r['event_observation'] for r in rows]
    times = [s['monotonic_us'] for s in sources]
    # A five-foot dial and a 0.1-foot combined endpoint tolerance. Sampling
    # determines which extra comparisons to try, never which turn occurred.
    capacity = number(policy['capacity_cfh'])
    gaps = [(times[j]-times[j-1], j) for j in range(1, len(times))
            if (times[j]-times[j-1])*capacity >= 4800000*3600]
    if not gaps:
        return edges
    # Cached positions only rank candidate pairs. Every selected movement is
    # independently read with the ordinary source and observation checks below.
    hints = db.execute("""
        SELECT b.event_id,b.context,json_extract(k.result,'$.dial_positions[#-2].position'),
               json_extract(k.result,'$.dial_positions[#-1].position')
        FROM event_recognition_bindings b JOIN event_recognition_cache k
        ON k.source_sha=b.source_sha AND k.pipeline=b.pipeline AND k.mask_sha=b.mask_sha
        WHERE b.event_id BETWEEN ? AND ? AND b.pipeline=?
        AND length(CAST(k.result AS BLOB))<=262144""",
        (sources[0]['event_id'],sources[-1]['event_id'],policy['pipeline_id']))
    indices = {(s['event_id'],s['context_id']):i for i,s in enumerate(sources)}
    positions = {}
    for event,context,slow,fast in hints:
        budget.spend()
        i = indices.get((event,context))
        if i is not None and type(slow) in (int,float) and type(fast) in (int,float):
            positions[i] = (slow*100,fast/2)
    residual = {}
    previous = None
    motion = 0
    for i,(slow,phase) in sorted(positions.items()):
        if previous is not None:
            motion += (phase-previous+2.5)%5-2.5
        residual[i] = motion-slow
        previous = phase
    # A missed revolution in the ranking proxy can lose an opportunity to
    # tighten. The proxy never supplies a constraint or selects a usage path.
    def extrema(start,stop,highest):
        buckets = {}
        for i in range(start,stop):
            budget.spend()
            if i not in residual:
                continue
            key=(sources[i]['context_id'],times[i]//60000000)
            prev=buckets.get(key)
            if prev is None or (residual[i]>residual[prev] if highest else residual[i]<residual[prev]):
                buckets[key]=i
        return list(buckets.values())
    pairs=set()
    for _,j in sorted(gaps,reverse=True)[:12]:
        left=bisect.bisect_left(times,times[j-1]-3600000000)
        right=bisect.bisect_right(times,times[j]+3600000000)
        ends=extrema(j,right,True)
        best={}
        for a in extrema(left,j,False):
            for b in ends:
                budget.spend()
                if (times[b]-times[a]>3600000000 or
                    any(sources[a][k]!=sources[b][k] for k in ('camera','clock_id','format_id','context_id')) or
                    abs(positions[b][0]-positions[a][0])>27):
                    continue
                key=sources[a]['context_id']
                candidate=(residual[b]-residual[a],a,b)
                if key not in best or candidate>best[key]:
                    best[key]=candidate
        pairs.update((a,b) for _,a,b in best.values())
    needed = sorted({i for pair in pairs for i in pair})
    values = dict(zip(needed, evidence(db, [rows[i] for i in needed], policy, budget)))
    allowance = number(policy['slow_allowance_ft3'])
    for a,b in sorted(pairs):
        movement = values[b]-values[a]
        if abs(movement) <= 27:
            edges.append((sources[a]['event_id'], sources[b]['event_id'],
                          max(0,movement-allowance), movement+allowance))
    return edges


def bounded_read(path, limit):
    if path.is_symlink() or not path.is_file():
        raise ValueError('missing reviewed evidence')
    with path.open('rb') as stream:
        data = stream.read(limit+1)
    if len(data) > limit:
        raise ValueError('oversize reviewed evidence')
    return data


def reviewed_edges(db, root, policy, start, through, segment, budget):
    """Every estimate publication revalidates the specific reviewed sources."""
    from daily_records import daily_records
    root = Path(root)
    body = bounded_read(root / REVIEW_FILE, 32768)
    doc = json.loads(body)
    if (set(doc) != {'version','pipeline_id','origin','intervals'} or type(doc['version']) is not int or
            doc['version'] != 1 or doc['pipeline_id'] != policy['pipeline_id'] or
            doc['origin'] != start or not isinstance(doc['intervals'],list) or
            not 1 <= len(doc['intervals']) <= 8):
        raise ValueError('incompatible movement review')
    out = []
    has_photo = False
    allowances = set()
    for review in doc['intervals']:
        budget.spend()
        if set(review) != {'endpoints','movement_ft3','allowance_ft3','kind'}:
            raise ValueError('invalid review fields')
        endpoints = review['endpoints']
        if len(endpoints) != 2:
            raise ValueError('expected two endpoints')
        left, right = endpoints
        if not (start <= left['event_id'] < right['event_id'] <= through):
            raise ValueError('outside publication period')
        if (left['format_id'] != policy['format_id'] or
            not 0 < right['monotonic_us']-left['monotonic_us'] <= 3600000000 or
            any(left[k] != right[k] for k in ('context_id','clock_id','camera','format_id'))):
            raise ValueError('review crosses sources')
        rows = []
        for endpoint in endpoints:
            e = endpoint['event_id']
            matches = list(daily_records(db,e,e,segment))
            if len(matches)!=1 or matches[0]['event_observation'] != endpoint:
                raise ValueError('review source mismatch')
            rows.append(matches[0])
        kind = review['kind']
        movement = number(review['movement_ft3'])
        if kind == 'pointer_photos':
            for source in endpoints:
                digest = source['source_sha256']
                if len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):
                    raise ValueError('invalid photo digest')
                raw = bounded_read(root/'images'/(digest+'.jpg'),1048576)
                if hashlib.sha256(raw).hexdigest()!=digest:
                    raise ValueError('reviewed image mismatch')
            has_photo = True
        elif kind == 'saved_slow_readings':
            first,last = evidence(db,rows,policy,budget)
            if abs(last-first-movement)>number('0.000001'):
                raise ValueError('reviewed dial movement mismatch')
        else:
            raise ValueError('unknown review kind')
        allowance = number(review['allowance_ft3'])
        if abs(movement)>27 or not 4<=allowance<=100 or movement+allowance<0:
            raise ValueError('invalid movement allowance')
        allowances.add(allowance)
        out.append((left['event_id'],right['event_id'],max(0,movement-allowance),movement+allowance))
    if not has_photo or len(allowances)!=1:
        raise ValueError('estimate requires photos and a common reviewed allowance')
    return out, hashlib.sha256(body).hexdigest(), allowances.pop()
