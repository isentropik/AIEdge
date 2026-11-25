"""Estimate chart-only movement between exposures separated by a failed capture."""
from datetime import datetime
from math import ceil, floor, isfinite
import sqlite3

from capture_clock import interval
from event_observation_read import read_batch
from meter_history import millis
from observation_support import observed_rows
from reading_bounds import feasible_ranges
from reading_format import validate


def offset(value, base, turn):
    return (value-base+turn/2) % turn-turn/2


def estimate(before, after, seconds, fine_turn, coarse_turn, fine_error, coarse_error, rate):
    """Pick the minimum forward turn only when adjacent poses and the larger dial agree.

    The independent envelope still includes every turn allowed by the calibrated
    errors and flow ceiling. Samples on each side are ordered (coarse, fine).
    """
    if not before or not after or seconds <= 0:
        return None
    limit = rate * seconds
    # Above half a coarse revolution its observed direction is itself ambiguous.
    if limit + 2*coarse_error >= coarse_turn/2:
        return None
    left, right = before[-1], after[0]
    coarse = offset(right[0], left[0], coarse_turn)
    fine = right[1]-left[1]
    low, high = max(0, coarse-2*coarse_error), min(limit, coarse+2*coarse_error)
    if low > high:
        return None
    k0 = ceil((low-fine-2*fine_error)/fine_turn)
    k1 = floor((high-fine+2*fine_error)/fine_turn)
    if k0 > k1:
        return None
    center = fine+k0*fine_turn
    bounds = [max(low,center-2*fine_error),min(high,fine+k1*fine_turn+2*fine_error)]
    if k0 != k1:
        if len(before)<2 or len(after)<2:
            return None
        coarse_spread = 0
        for side in (before,after):
            co = [offset(p[0],side[0][0],coarse_turn) for p in side]
            fi = [offset(p[1],side[0][1],fine_turn) for p in side]
            coarse_spread = max(coarse_spread,max(co)-min(co))
            if max(fi)-min(fi)>2*fine_error:
                return None
        if abs(coarse-center)+coarse_spread+2*fine_error >= fine_turn/2:
            return None
    return dict(use=min(bounds[1],max(bounds[0],center)),bounds=bounds,
                selected_bounds=[bounds[0],min(bounds[1],center+2*fine_error)])


def photo_gaps(store, start, stamp, state, document, rate):
    if not state or not document or not rate or len(document['dials'])<2:
        return []
    revision=validate(document)[1]
    pipeline=document['pipeline_id']
    coarse,fine=document['dials'][-2:]
    ct,ft=coarse['value_per_revolution'],fine['value_per_revolution']
    ce,fe=ct*coarse['position_error']/10,ft*fine['position_error']/10
    with store.connect() as db:
        tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'capture_failure_boundaries','event_recognition_bindings','capture_clocks'} <= tables:
            return []
        head=db.execute('SELECT e.camera FROM capture_events e JOIN frames f USING(camera,frame_id) '
                        'WHERE e.event_id=? AND f.sha256=? AND f.captured_at=?',
                        (state.get('event_id'),state.get('source_sha256'),state.get('measured_at'))).fetchone()
        if not head:
            return []
        camera=head[0]
        rows=db.execute('''SELECT t.id, f.captured_at,g.captured_at FROM
            (SELECT DISTINCT after_event_id AS id FROM capture_failure_boundaries WHERE outcome='unknown'
             AND after_event_id<?) t CROSS JOIN capture_events e ON e.event_id=t.id
            CROSS JOIN capture_events n ON n.event_id=t.id+1 AND n.camera=e.camera
            CROSS JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id
            CROSS JOIN frames g ON g.camera=n.camera AND g.frame_id=n.frame_id
            WHERE e.camera=? AND g.captured_at>=? ORDER BY t.id''',
            (state['event_id'],camera,start.isoformat())).fetchall()
        gaps=[]
        for eid,left,right in rows:
            a,b=(millis(datetime.fromisoformat(t)) for t in (left,right))
            elapsed=(b-a)/1000
            if b>stamp or elapsed<=0:
                continue
            gap=dict(start=a,end=b,events=[eid,eid+1])
            gaps.append(gap)
            refs=db.execute('SELECT b.event_id,b.context,b.source_sha FROM event_recognition_bindings b '
                            'JOIN capture_events e USING(event_id) WHERE b.pipeline=? AND e.camera=? '
                            'AND b.event_id BETWEEN ? AND ? ORDER BY b.event_id',
                            (pipeline,camera,eid-2,min(state['event_id'],eid+3))).fetchall()
            if len(refs)!=len({r[0] for r in refs}):
                continue
            poses={}
            absolute={}
            try:
                for item in read_batch(db,[dict(event_id=i,context_id=c,source_sha256=s) for i,c,s in refs],pipeline) if refs else ():
                    reading=item['result']
                    obs=reading['event_observation']
                    mask=observed_rows(reading)
                    indices=(coarse['index'],fine['index'])
                    if (reading['state']!='estimated' or obs['format_id']!=revision or obs['camera']!=camera or
                            millis(datetime.fromisoformat(obs['captured_at']))>stamp or
                            not all(mask[i] for i in indices)):
                        continue
                    vals=[reading['dial_positions'][i]['position'] for i in indices]
                    if all(isinstance(v,(int,float)) and isfinite(v) and 0<=v<10 for v in vals):
                        poses[obs['event_id']]=(obs,(vals[0]*ct/10,vals[1]*ft/10))
                        if obs['event_id'] in (eid,eid+1) and all(mask):
                            dials=document['dials']
                            ranges=feasible_ranges([d['value_per_revolution'] for d in dials],
                                [reading['dial_positions'][d['index']]['position'] for d in dials],
                                [d['position_error'] for d in dials])
                            absolute[obs['event_id']]=[(float(lo),float(hi)) for lo,hi in ranges.get('intervals',())]
            except (ValueError,TypeError,KeyError,IndexError,sqlite3.Error):
                continue
            if eid not in poses or eid+1 not in poses:
                continue
            first,last=poses[eid][0],poses[eid+1][0]
            if first['context_id']!=last['context_id'] or (first['captured_at'],last['captured_at'])!=(left,right):
                continue
            if first['clock_id']==last['clock_id'] and interval(first,last)['state']!='continuous':
                continue
            def flank(ids, edge):
                side=[]
                for i in ids:
                    if i not in poses:
                        break
                    obs,p=poses[i]
                    if (obs['clock_id']!=edge['clock_id'] or obs['context_id']!=edge['context_id'] or
                            abs(obs['monotonic_us']-edge['monotonic_us'])>180_000_000):
                        break
                    if i!=edge['event_id']:
                        early,late=(obs,edge) if i<edge['event_id'] else (edge,obs)
                        if interval(early,late)['state']!='continuous':
                            break
                    side.append(p)
                return side
            before=flank(range(eid,eid-3,-1),first)[::-1]
            after=flank(range(eid+1,eid+4),last)
            motion=estimate(before,after,elapsed,ft,ct,fe,ce,rate)
            if any(not bands for bands in absolute.values()):
                continue
            if motion and len(absolute)==2:
                lo,hi=motion['bounds']
                ranges=[(max(lo,y0-x1),min(hi,y1-x0)) for x0,x1 in absolute[eid] for y0,y1 in absolute[eid+1]]
                ranges=[(a,b) for a,b in ranges if a<=b]
                choice=next(((a,b) for a,b in ranges if a-1e-8<=motion['use']<=b+1e-8),None)
                if choice is None:
                    continue
                motion['use']=max(choice[0],min(choice[1],motion['use']))
                motion['bounds']=[min(a for a,_ in ranges),max(b for _,b in ranges)]
                selected_lo,selected_hi=motion['selected_bounds']
                selected=[(max(a,selected_lo),min(b,selected_hi)) for a,b in ranges if a<=selected_hi and selected_lo<=b]
                if not selected:
                    continue
                motion['selected_bounds']=[min(a for a,_ in selected),max(b for _,b in selected)]
            if motion:
                gap.update(motion)
        return gaps
