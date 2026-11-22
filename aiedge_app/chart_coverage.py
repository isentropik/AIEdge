"""Capture continuity for the hourly display, independent of MQTT publication cadence."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from meter_history import millis


def read_coverage(store,daily,track,cached=None):
    opening=daily['after']
    source=daily['through']
    camera=source['camera']
    if opening['camera']!=camera or opening['format_id']!=source['format_id']:
        raise ValueError('chart source differs at opening')
    def endpoint(s):
        return [s['event_id'],millis(datetime.fromisoformat(s['captured_at']))]
    first=endpoint(opening)
    target=endpoint(source)
    local = ZoneInfo(daily['timezone'])
    day = date.fromisoformat(daily['day'])
    midnight = millis(datetime.combine(day, time.min, local))
    if not all(datetime.fromisoformat(s['captured_at']).astimezone(local).date() == day
               for s in (opening, source)):
        raise ValueError('capture range crosses the selected day')
    if track and track.get('points'):
        if track.get('format') != source['format_id'] or track.get('midnight') != midnight:
            raise ValueError('movement history differs from the daily range')
        stamp,_,event,_=track['points'][-1]
        if datetime.fromtimestamp(stamp/1000, local).date() != day:
            raise ValueError('movement endpoint is from another day')
        if event>target[0]:target=[event,stamp]
    if target[0]<first[0] or target[1]<first[1]:
        raise ValueError('invalid chart window')
    previous=None
    gaps=[]
    begin=first[0]
    with store.connect() as db:
        # Bind both ends of the range publication to the saved camera and frame.
        for s in (opening,source):
            frame=db.execute("""SELECT f.captured_at,f.sha256 FROM capture_events e JOIN frames f
                USING (camera,frame_id) WHERE e.event_id=? AND e.camera=?""",(s['event_id'],camera)).fetchone()
            if frame!=(s['captured_at'],s['source_sha256']):
                raise ValueError('unbound chart range')
        if cached and cached['first']==first and first[0]<=cached['through'][0]<=target[0]:
            begin=cached['through'][0]
            gaps=list(cached['gaps'])
        failures={r[0] for r in db.execute('SELECT DISTINCT after_event_id FROM capture_failure_boundaries WHERE after_event_id>=? AND after_event_id<?',(begin,target[0]))}
        segments={r[0] for r in db.execute('SELECT first_event FROM consumption_segments WHERE format_id=? AND first_event>? AND first_event<=?',(source['format_id'],begin,target[0]))}
        # Read only frame IDs and timestamps in short pages. No image or inference payload.
        for lo in range(begin,target[0]+1,512):
            rows=db.execute("""SELECT e.event_id,f.captured_at FROM capture_events e JOIN frames f
                USING (camera,frame_id) WHERE e.camera=? AND e.event_id BETWEEN ? AND ?
                ORDER BY e.event_id""",(camera,lo,min(lo+511,target[0]))).fetchall()
            for eid,stamp in rows:
                t=datetime.fromisoformat(stamp)
                if t.utcoffset() is None:raise ValueError('unbound frame time')
                ms=millis(t)
                if previous is None:
                    expected=first if begin==first[0] else cached['through']
                    if [eid,ms]!=expected:raise ValueError('archive opening mismatch')
                else:
                    old,at,old_ms=previous
                    if t<=at:raise ValueError('out of order capture time')
                    if old in failures or eid in segments or eid!=old+1 or t-at>=timedelta(minutes=11):
                        gaps.append([old_ms,ms])
                previous=eid,t,ms
    if not previous or [previous[0],previous[2]]!=target:raise ValueError('archive endpoint mismatch')
    return dict(first=first,through=target,gaps=gaps)
