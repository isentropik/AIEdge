"""Explicit human-reviewed photo sectors; read-only constraints, never ledger rows."""
import bisect
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from daily_constraints import bands, number, propagate

NAME = 'reviewed-photo-constraints.json'
SOURCE = ('event_id', 'camera', 'source_sha256', 'captured_at', 'clock_id', 'monotonic_us')
FIELDS = set(SOURCE) | {'review_id', 'format_id', 'pipeline_id', 'phase_lower_ft3', 'phase_upper_ft3'}


def load(root):
    try:
        return _load(root)
    except (ArithmeticError, TypeError, KeyError, RecursionError, UnicodeError) as exc:
        raise ValueError('invalid reviewed photo manifest') from exc


def _load(root):
    path = Path(root) / NAME
    try:
        if path.is_symlink():
            raise ValueError('reviewed photo manifest symlink')
        with path.open('rb') as stream:
            body = stream.read(32769)
    except FileNotFoundError:
        return []
    if len(body) > 32768:
        raise ValueError('reviewed photo manifest too large')
    def unique(pairs):
        value = {}
        for k, v in pairs:
            if k in value:
                raise ValueError('duplicate reviewed photo field')
            value[k] = v
        return value
    doc = json.loads(body, object_pairs_hook=unique)
    if (not isinstance(doc, dict) or set(doc) != {'schema_version', 'reviews'}
            or type(doc['schema_version']) is not int or doc['schema_version'] != 1
            or not isinstance(doc['reviews'], list) or len(doc['reviews']) > 8):
        raise ValueError('invalid reviewed photo manifest')
    ids, events = set(), set()
    for r in doc['reviews']:
        if not isinstance(r, dict) or set(r) != FIELDS:
            raise ValueError('invalid reviewed photo fields')
        if (not isinstance(r['review_id'], str) or not re.fullmatch(r'[a-z0-9_-]{1,80}', r['review_id'])
                or r['review_id'] in ids or r['event_id'] in events):
            raise ValueError('duplicate or invalid photo review')
        for k in ('event_id', 'monotonic_us'):
            if type(r[k]) is not int or r[k] <= 0:
                raise ValueError('invalid photo source number')
        for k, size in (('source_sha256', 64), ('format_id', 64), ('pipeline_id', 64), ('clock_id', 32)):
            if not isinstance(r[k], str) or not re.fullmatch('[a-f0-9]{' + str(size) + '}', r[k]):
                raise ValueError('invalid photo source digest')
        if not isinstance(r['camera'], str) or not 1 <= len(r['camera']) <= 4096:
            raise ValueError('invalid photo camera identity')
        if not isinstance(r['captured_at'], str) or datetime.fromisoformat(r['captured_at']).utcoffset() is None:
            raise ValueError('invalid photo timestamp')
        if not 0 <= number(r['phase_lower_ft3']) <= number(r['phase_upper_ft3']) <= 5:
            raise ValueError('invalid photo phase sector')
        ids.add(r['review_id']); events.add(r['event_id'])
    return doc['reviews']


def constraints(db, rows, document, policy, budget):
    root = Path(db.execute('PRAGMA database_list').fetchone()[2]).parent
    reviews = load(root)
    if not reviews:
        return [], []
    if number(document['dials'][-1]['value_per_revolution']) != 5:
        raise ValueError('photo review geometry changed')
    events = [r['event_observation']['event_id'] for r in rows]
    extra, used = [], []
    modulus = number(document['dials'][0]['value_per_revolution'])
    rate = min(number(document['maximum_rate_per_second']), number(policy['capacity_cfh']) / 3600)
    for review in reviews:
        budget.spend()
        j = bisect.bisect_left(events, review['event_id'])
        # A reviewed intermediate photo supplements accepted endpoints; it is
        # never inserted into daily_records or substituted for accepted inference.
        if not 0 < j < len(rows) or events[j] == review['event_id']:
            continue
        left, right = rows[j-1], rows[j]
        x, y = left['event_observation'], right['event_observation']
        if (review['format_id'] != policy['format_id'] or review['pipeline_id'] != policy['pipeline_id']
                or any(review[k] != x[k] or review[k] != y[k] for k in ('camera', 'clock_id', 'format_id'))):
            raise ValueError('photo review identity changed')
        first = review['monotonic_us'] - x['monotonic_us']
        second = y['monotonic_us'] - review['monotonic_us']
        if not (0 < first and 0 < second and first + second <= 60000000):
            continue  # Longer gaps remain unsupported by this bounded projector.
        if not datetime.fromisoformat(x['captured_at']) < datetime.fromisoformat(review['captured_at']) < datetime.fromisoformat(y['captured_at']):
            raise ValueError('photo wall clock ordering changed')
        saved = db.execute('''SELECT e.event_id,e.camera,f.sha256,f.captured_at,c.clock_id,c.monotonic_us
          FROM capture_events e JOIN frames f USING(camera,frame_id)
          JOIN capture_clocks c USING(camera,frame_id) WHERE e.event_id=?''', (review['event_id'],)).fetchone()
        if saved is None or tuple(review[k] for k in SOURCE) != tuple(saved):
            raise ValueError('photo acquisition mismatch')
        path = root / 'images' / (review['source_sha256'] + '.jpg')
        if path.is_symlink():
            raise ValueError('photo evidence symlink')
        with path.open('rb') as stream:
            body = stream.read(1048577)
        if len(body) > 1048576 or hashlib.sha256(body).hexdigest() != review['source_sha256']:
            raise ValueError('photo evidence hash mismatch')
        lb, rb = bands(left, modulus), bands(right, modulus)
        if lb is None or rb is None:
            continue
        c1, c2 = number(first) * rate / 1000000, number(second) * rate / 1000000
        lo, hi = number(review['phase_lower_ft3']), number(review['phase_upper_ft3'])
        limits = []
        for a, b in lb:
            for c, d in rb:
                first_turn = int(((a-hi)/5).to_integral_value(rounding=ROUND_FLOOR))
                last_turn = int(((min(b+c1,d)-lo)/5).to_integral_value(rounding=ROUND_FLOOR))
                if last_turn-first_turn > 64:
                    raise ValueError('photo projector work limit')
                for turn in range(first_turn, last_turn+1):
                    budget.spend()
                    middle = (number(turn*5)+lo, number(turn*5)+hi)
                    z = propagate([[(a,b)],[middle],[(c,d)]],
                                  [(0,1,Decimal(0),c1),(1,2,Decimal(0),c2)],
                                  [[0],[0,1],[1]], budget)
                    if z:
                        limits.append((max(Decimal(0),z[2][0][0]-z[0][0][1]),
                                       min(c1+c2,z[2][0][1]-z[0][0][0])))
        if not limits:
            raise ValueError('photo review contradicts saved readings')
        edge = (events[j-1], events[j], min(v[0] for v in limits), max(v[1] for v in limits))
        extra.append(edge)
        used.append(dict(review_id=review['review_id'], event_id=review['event_id'],
                         source_sha256=review['source_sha256'], captured_at=review['captured_at'],
                         basis='human_reviewed_broad_pointer_sector', left_event=edge[0], right_event=edge[1]))
    return extra, used

