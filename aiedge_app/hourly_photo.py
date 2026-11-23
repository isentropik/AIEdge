"""Recover an absolute hour boundary from retained photos and saved dial observations."""
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import json

from absolute_motion import start as start_register
from capture_clock import interval
from daily_constraints import number
from dial_travel import phases
from event_observation_read import read_batch
from observation_support import observed_rows
from reading_bounds import diagnose_inconsistency


def photo_anchor(db, reader, document, source, eid):
    pipeline = document['pipeline_id']
    bindings = db.execute('SELECT context,source_sha FROM event_recognition_bindings '
                          'WHERE event_id=? AND pipeline=?',(eid,pipeline)).fetchall()
    if len(bindings)!=1:
        return None
    context,digest = bindings[0]
    request = dict(event_id=eid,context_id=context,source_sha256=digest)
    inference = read_batch(db,[request],pipeline)[0]['result']
    obs = inference.get('event_observation') or {}
    if (inference.get('state')!='estimated' or obs.get('event_id')!=eid or
            any(obs.get(k)!=source[k] for k in ('camera','format_id')) or
            observed_rows(inference)!=[True]*len(document['dials'])):
        return None
    records = db.execute('SELECT result FROM consumption_records WHERE segment_id IN '
                         '(SELECT segment_id FROM consumption_segments WHERE format_id=? AND first_event<=?) '
                         'AND event_id=?',(source['format_id'],eid,eid)).fetchall()
    if len(records)!=1:
        return None
    record = json.loads(records[0][0])
    if record.get('event_observation')!=obs or record.get('reason')!='consumption_positions_contradict_bounds':
        return None
    positions=[r['position'] for r in inference['dial_positions']]
    consistency=diagnose_inconsistency(document,positions)
    if consistency['state']!='inconsistent':
        return None
    raw=dict(state='inconsistent',reason='dial_bounds_disagree',consistency=consistency,
             format_id=source['format_id'],source_sha256=digest)
    proof=reader.check(dict(format=document,consumption=record,_raw_meter_reading=raw,
                            _publication_segment_id=record['segment_id'],_timing_event_id=eid,
                            latest=dict(captured_at=obs['captured_at'],sha256=digest)),inference)
    if not proof or 'photo_center_ft3' not in proof:
        return None
    bands=[tuple(map(number,pair)) for pair in proof['bands_ft3']]
    track=start_register(obs,bands,Decimal(0),photo_center=number(proof['photo_center_ft3']))
    if track:
        return obs,number(track['level']),tuple(map(number,track['outer']))


def project(db, document, source, rate, anchor, samples, travel):
    """Use movement bounds to assign one absolute turn to each measured phase."""
    ref,base,(base_lo,base_hi)=anchor
    when=datetime.fromisoformat(ref['captured_at'])
    turn=min(number(d['value_per_revolution']) for d in document['dials'])
    result=[]
    for obs,band in samples:
        t=datetime.fromisoformat(obs['captured_at'])
        eid=obs['event_id']
        if eid==ref['event_id']:
            result.append((base,base_lo,base_hi))
            continue
        else:
            first,last=(ref,obs) if when<t else (obs,ref)
            movement=travel(db,source,document,rate,min(when,t),max(when,t),first['event_id'],last['event_id'])
            if not movement or 'use' not in movement or movement['supported_spans']:
                return None
            lo,hi=map(number,movement['bounds'])
            if t<when:
                lo,hi=-hi,-lo
        phase=sum(band)/2
        low_turn=((base+lo-phase)/turn).to_integral_value(rounding=ROUND_CEILING)
        high_turn=((base+hi-phase)/turn).to_integral_value(rounding=ROUND_FLOOR)
        if low_turn!=high_turn:
            return None
        result.append((phase+low_turn*turn,base_lo+lo,base_hi+hi))
    if len(result)==2 and result[1][0]<result[0][0]:
        # Optical centers can jitter backward on a stationary pointer. A
        # common level must fit both observed fine-dial bands on these turns.
        bands=[]
        for (value,_,_),(_,(lo,hi)) in zip(result,samples):
            shift=((value-(lo+hi)/2)/turn).to_integral_value()*turn
            bands.append((lo+shift,hi+shift))
        low=max(lo for lo,_ in bands)
        high=min(hi for _,hi in bands)
        if high<low:
            return None
        level=(low+high)/2
        if not all(lo<=level<=hi for _,lo,hi in result):
            return None
        return [(level,lo,hi) for _,lo,hi in result]
    return result


def recover_boundary(db, reader, document, source, rate, t, before, after, first, last, travel,cache, reference=None):
    """Require supported hour brackets. Use an independent photo from either side."""
    if before is None or after is None or after-before not in (0,1):
        return None
    data=phases(db,before,after,document,source,same_clock=False)
    ids=[before] if before==after else [before,after]
    if any(eid not in data for eid in ids):
        return None
    samples=[data[eid] for eid in ids]
    a,b=samples[0][0],samples[-1][0]
    left,right=(datetime.fromisoformat(s['captured_at']) for s in (a,b))
    if not left<=t<=right:
        return None
    if before!=after and (after!=before+1 or a['context_id']!=b['context_id'] or
                          interval(a,b)['state']!='continuous' or (right-left).total_seconds()>=660):
        return None
    # Keep both the interpolation and all anchor propagation in one uninterrupted run.
    breaks=[r[0] for r in db.execute('SELECT after_event_id+1 FROM capture_failure_boundaries '
        'WHERE after_event_id BETWEEN ? AND ? UNION SELECT first_event FROM consumption_segment_links '
        'WHERE first_event BETWEEN ? AND ?', (first,last-1,first+1,last))]
    if any(before<cut<=after for cut in breaks):
        return None
    first=max([first]+[cut for cut in breaks if cut<=before])
    last=min([last]+[cut-1 for cut in breaks if cut>after])
    estimates=[]
    calibration=reader.setup.status().get('revision')
    for lo,hi,order in ((first,before,'DESC'),(after,last,'ASC')):
        candidates=db.execute('SELECT e.event_id FROM capture_events e JOIN frames f USING(camera,frame_id) '
            'WHERE e.camera=? AND e.event_id BETWEEN ? AND ? AND NOT EXISTS '
            '(SELECT 1 FROM retired_images r WHERE r.sha256=f.sha256) ORDER BY e.event_id '+order+' LIMIT 4',
            (source['camera'],lo,hi)).fetchall()
        for (eid,) in candidates:
            key=(source['camera'],source['format_id'],calibration,rate,eid,before,after)
            pair=cache.get(key)
            if pair is None:
                try:
                    anchor=photo_anchor(db,reader,document,source,eid)
                except (KeyError,IndexError,TypeError,ValueError,OSError,ArithmeticError):
                    # A missing image or an older unbound recognition cannot anchor an hour.
                    continue
                if not anchor:
                    continue
                pair=project(db,document,source,rate,anchor,samples,travel)
                if pair:
                    if len(cache)>=64:
                        cache.pop(next(iter(cache)))
                    cache[key]=pair
            if not pair or pair[-1][0]<pair[0][0]:
                continue
            weight=number((t-left).total_seconds())/number((right-left).total_seconds()) if left!=right else Decimal(0)
            level=pair[0][0]+weight*(pair[-1][0]-pair[0][0])
            estimates.append((level,pair[0][1],pair[-1][2],eid,pair))
            break
    if not estimates:
        return None
    lo=max(row[1] for row in estimates)
    hi=min(row[2] for row in estimates)
    # Keep every photo's outer bounds. A separate absolute reading propagated
    # through measured hours can corroborate one of the proposed nominal turns.
    if reference is not None:
        estimates=[row for row in estimates if abs(row[0]-reference)<=Decimal('.01')]
    if not estimates:
        return None
    level,_,_,_,pair=estimates[0]
    if not lo<=level<=hi or any(abs(other[0]-level)>Decimal('.01') for other in estimates):
        return None
    return dict(value=level,bounds=(lo,hi),anchors=list(dict.fromkeys(r[3] for r in estimates)),
                frames=[dict(event=s['event_id'],time=s['captured_at'],sha256=s['source_sha256'],value=float(p[0]))
                        for (s,_),p in zip(samples,pair)])


def recorded_endpoint(db, source, reading):
    if reading[2][1]!='photo_anchored_fine_dial' or not reading[1]:
        return None
    for eid,digest in reading[3]:
        if not db.execute('SELECT 1 FROM capture_events e JOIN frames f USING(camera,frame_id) '
                'JOIN event_recognition_bindings b USING(event_id) JOIN event_selection_contexts c ON '
                'c.context=b.context WHERE e.event_id=? AND e.camera=? AND f.sha256=? AND b.source_sha=f.sha256 '
                'AND c.format_id=?',(eid,source['camera'],digest,source['format_id'])).fetchone():
            return None
    return dict(value=reading[0],bounds=reading[1])


def difference(left,right):
    if not left or not right or right['value']<left['value']:
        return None
    delta=right['value']-left['value']
    lo=max(Decimal(0),right['bounds'][0]-left['bounds'][1])
    hi=right['bounds'][1]-left['bounds'][0]
    if not lo<=delta<=hi:
        return None
    cent=Decimal('.01')
    proof={name:{k:r[k] for k in ('frames','anchors')} for name,r in
           (('opening',left),('closing',right)) if 'frames' in r}
    return dict(use=float(delta),basis='photo_replay',opening=float(left['value']),closing=float(right['value']),
                bounds=[float(lo.quantize(cent,rounding=ROUND_FLOOR)),float(hi.quantize(cent,rounding=ROUND_CEILING))],
                photo_evidence=proof)


def carried_difference(anchor, movement, closing):
    """Position the opening register using one independently measured preceding hour."""
    if not anchor or not closing or movement.get('basis')!='fine_dial' or 'use' not in movement:
        return None
    use = number(movement['use'])
    low, high = map(number, movement['bounds'])
    if not 0 <= low <= use <= high:
        return None
    opening = dict(value=anchor['value']+use,
                   bounds=(anchor['bounds'][0]+low, anchor['bounds'][1]+high))
    hour = difference(opening, closing)
    if hour:
        hour['basis'] = 'carried_register'
        hour['carry'] = dict(start=movement['start'], end=movement['end'],
                             reading=float(anchor['value']), use=float(use))
        if 'frames' in anchor:
            hour['photo_evidence']['anchor'] = {k:anchor[k] for k in ('frames','anchors')}
        if 'reference_time' in anchor:
            hour['carry'].update(reference_time=anchor['reference_time'],reference_value=anchor['reference_value'])
    return hour
