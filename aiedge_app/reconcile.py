"""Rebuild only the absolute register from retained original evidence and measured phases."""
from contextlib import closing,contextmanager
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from absolute_motion import meter_rate, update
from original_meter import OriginalMeter
from register_replay import refine
from reading_format import validate

class EvidenceStore:
    def __init__(self,path):
        self.uri=Path(path).resolve().as_uri()+'?mode=ro'
    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.uri,uri=True)) as db:
            yield db
    def image(self,digest):
        raise FileNotFoundError(digest)

def rebuild(store,document,pre_gap,active,anchor,target,failed_attempt,*,on_point=None):
    originals=OriginalMeter(store,None)
    old=pre_gap['absolute_motion']
    first=old['source']['event_id']
    motion=active['absolute_motion']
    old_anchor=motion['anchor']
    end=target['event_id']
    if not first<anchor['event_id']<=old_anchor['event_id']<=end:
        raise ValueError('unexpected checkpoint order')
    if old['display']['event_id']!=first or old['needs_confirmation'] or target!=motion['source']:
        raise ValueError('unconfirmed or mismatched checkpoint')
    fmt=validate(document)[1]
    if active['format_id']!=pre_gap['format_id'] or fmt!=active['format_id'] or active['source_identity']!=pre_gap['source_identity']:
        raise ValueError('meter identity changed')
    rate=meter_rate(document)
    with store.connect() as db:
        binding=db.execute('SELECT a.after_event_id,o.outcome,o.event_id,o.error FROM continuous_capture_attempts a '
                           'JOIN continuous_capture_outcomes o USING(attempt_id) WHERE a.attempt_id=?',(failed_attempt,)).fetchone()
        if binding!=(first,'unknown',None,'camera_timeout'):
            raise ValueError('unexpected capture failure')
        if db.execute('SELECT pending FROM retired_images WHERE sha256=?',(anchor['source_sha256'],)).fetchone()!=(0,):
            raise ValueError('expected an expired original')
        cuts=db.execute('SELECT after_event_id FROM capture_failure_boundaries WHERE after_event_id>=? AND after_event_id<? ORDER BY 1',(first,end)).fetchall()
        links=db.execute('SELECT first_event,unresolved_gap_reason FROM consumption_segment_links WHERE first_event>? AND first_event<=? ORDER BY 1',(first,end)).fetchall()
        if cuts!=[(first,)] or links!=[(first+1,'capture_failure')]:
            raise ValueError('changed capture boundaries')
        records=db.execute('SELECT event_id,segment_id,result FROM consumption_records WHERE event_id BETWEEN ? AND ? ORDER BY event_id',
                           (anchor['event_id'],end)).fetchall()
    if len(records)!=end-anchor['event_id']+1: raise ValueError('missing or duplicate observation')
    segment=records[0][1]
    snap=dict(format=document,_publication_segment_id=segment)
    previous=old
    for i,(eid,seg,raw) in enumerate(records,anchor['event_id']):
        record=json.loads(raw)
        source=record['event_observation']
        if i!=eid or source['event_id']!=eid or seg!=segment or source['format_id']!=fmt:
            raise ValueError('observation identity changed')
        if record.get('unresolved_gap')!={'reason':'capture_failure','first_event':first+1,'delta':None}:
            raise ValueError('gap accounting changed')
        if eid==anchor['event_id']:
            if source['source_sha256']!=anchor['source_sha256']: raise ValueError('wrong original')
            for _ in range(1+(eid-first)//4+1):
                candidate=originals.recover(old,pre_gap,pre_gap.get('photo_register') or {},snap,source,rate=rate)
                if candidate!=old: break
            if candidate['anchor']!=source: raise ValueError('restored original cannot anchor recovery')
        else:
            candidate=update(previous,store,snap,source,None,Decimal(pre_gap.get('photo_register',{}).get('value_ft3',0)),rate=rate)
        if candidate['source']!=source or candidate.get('needs_confirmation') or candidate['anchor']['event_id']!=anchor['event_id']:
            raise ValueError(f'unsupported motion at exposure {eid}')
        candidate=refine(store,document,candidate,rate,originals)
        shown=candidate['display']
        if (shown['event_id']!=eid or Decimal(shown['value_ft3'])<Decimal(previous['display']['value_ft3'])
                or not Decimal(shown['lower_ft3'])<=Decimal(shown['value_ft3'])<=Decimal(shown['upper_ft3'])):
            raise ValueError(f'inconsistent meter or bounds at exposure {eid}')
        if on_point: on_point(dict(shown))
        previous=candidate
    if previous['source']!=target or Decimal(previous['display']['value_ft3'])<Decimal(motion['display']['value_ft3']):
        raise ValueError('replayed meter does not reach active checkpoint')
    return previous
