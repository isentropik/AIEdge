"""Read durable per-image inference for one bounded trial; no acquisition/writes."""
from capture_trial import ACTIVE,TERMINAL,decode_snapshot,limits
import json


def build(trial,recognition,request_id):
    limits(request_id,3,90,30)
    base=dict(request_id=request_id,frames=[],training_allowed=False,accuracy_verified=False)
    if trial is None:return dict(base,state='unavailable',error='trial_unavailable')
    snapshot=trial.status(request_id)
    if snapshot['state'] in ('not_found','unavailable'):
        return dict(base,state=snapshot['state'],error=snapshot.get('error'))
    # Reject corrupt/unbounded journals even if an alternative caller bypassed
    # CaptureTrial.status. Never query a substituted active pipeline.
    snapshot=decode_snapshot(request_id,json.dumps(snapshot,allow_nan=False))
    pipeline=snapshot['context'].get('pipeline_id')
    base.update(context=snapshot['context'],trial_state=snapshot['state'],
                counts_complete=snapshot['counts_complete'],
                capture_outcome_uncertain=snapshot['capture_outcome_uncertain'])
    if recognition is None or pipeline is None:
        return dict(base,state='unavailable',error='trial_reader_unavailable')
    # Repeated JPEGs share inference but retain all acquisition/frame identities.
    results={}
    for frame in snapshot['frames']:
        digest=frame['sha256']
        context=snapshot['context'].get('observation_context')
        with recognition.store.connect() as db:
            if context is not None:
                exists=db.execute('SELECT 1 FROM capture_events e JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id LEFT JOIN capture_clocks c ON c.camera=e.camera AND c.frame_id=e.frame_id WHERE e.event_id=? AND e.camera=? AND f.frame_id=? AND f.captured_at=? AND f.sha256=? AND c.clock_id IS ? AND c.monotonic_us IS ?',
                                  (frame['event_id'],frame['camera'],frame['frame_id'],frame['captured_at'],digest,frame['clock_id'],frame['monotonic_us'])).fetchone()
            else:
                exists=db.execute('SELECT 1 FROM frames WHERE frame_id=? AND captured_at=? AND sha256=? LIMIT 1',
                                  (frame['frame_id'],frame['captured_at'],digest)).fetchone()
        if not exists:
            value={'processed_at':None,'result':dict(state='unavailable',error='trial_frame_missing',
                source_sha256=digest,pipeline_id=pipeline,training_allowed=False,accuracy_verified=False)}
        else:
            if context is not None:
                from event_observation_read import read_event
                value=read_event(recognition.store,frame['event_id'],digest,pipeline,context)
            else:
                if digest not in results:results[digest]=recognition.stored(digest,pipeline)
                value=results[digest]
        base['frames'].append(dict(frame=frame,**value))
    severity={'estimated':0,'rejected':1,'pending':2,'unavailable':3}
    states={}
    for value in base['frames']:
        digest=value['frame']['sha256'];state=value['result']['state']
        if severity[state]>=severity.get(states.get(digest),-1):states[digest]=state
    counts={name:sum(value==name for value in states.values())
            for name in ('estimated','rejected','pending','unavailable')}
    frame_errors=any(value['result']['state']=='unavailable' for value in base['frames'])
    state=('unavailable' if frame_errors else 'pending'
           if snapshot['state'] in ACTIVE or counts['pending'] else 'complete')
    return dict(base,state=state,unique_images=snapshot['unique_images'],processing=counts,
                processing_complete=bool(snapshot['state'] in TERMINAL and not counts['pending'] and not frame_errors))
