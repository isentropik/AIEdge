"""Bound observation eligibility; never a physical continuity/rate certificate.

The producer's explicit acceptance witness is required. This reader joins the
immutable request/completion/cache/acquisition and accounting record; caller
persists the derived certificate in the NEXT request and rederives it on replay.
No models, native calls, image access, writes or accounting branch changes.
"""
import json
import capture_clock
from event_selection import digest
from event_observation_read import _read,_decode,MAX_REQUEST_BYTES
from observation_support import observed_rows
from reading_format import finite_number,validate

VERSION=1
MAX_RECORD_BYTES=65536
ACCEPTED_STATES={'anchored','estimated','within_noise','bounded','ambiguous'}

def check(ok,reason):
    if not ok:raise ValueError(reason)

def _load(worker,db,event,segment):
    acquisition=worker._event(db,event)
    check(acquisition is not None,'selector_observation_acquisition_missing')
    row=db.execute('SELECT CASE WHEN length(CAST(result AS BLOB))<=? THEN result END FROM consumption_records WHERE segment_id=? AND event_id=?',(MAX_RECORD_BYTES,segment,event)).fetchone()
    check(row is not None,'selector_observation_accounting_missing')
    record=_decode(row[0],MAX_RECORD_BYTES)
    check(isinstance(record,dict),'selector_observation_accounting_invalid')
    result=_read(db,event,acquisition['source_sha256'],worker.reader.pipeline_id,worker.observation_context)['result']
    check(result.get('state') in ('estimated','rejected'),'selector_observation_completion_missing')
    request_row=db.execute('SELECT CASE WHEN length(CAST(request AS BLOB))<=? THEN request END,request_sha FROM event_recognition_requests WHERE event_id=? AND pipeline=? AND context=?',
                           (MAX_REQUEST_BYTES,event,worker.reader.pipeline_id,worker.observation_context)).fetchone()
    request=_decode(request_row[0],MAX_REQUEST_BYTES)
    check(digest(request)==request_row[1],'selector_observation_request_invalid')
    expected={**{k:acquisition[k] for k in ('event_id','camera','captured_at','clock_id','monotonic_us','source_sha256')},
              'context_id':worker.observation_context,'format_id':worker.format_id,'request_sha256':request_row[1]}
    check(digest(record.get('event_observation'))==digest(expected) and digest(result.get('event_observation'))==digest(expected),'selector_observation_binding_invalid')
    check(record.get('segment_id')==segment and type(record.get('event_id')) is int and record.get('event_id')==event and
          record.get('source_sha256')==acquisition['source_sha256'] and record.get('format_id')==worker.format_id and
          record.get('observation_context')==worker.observation_context,'selector_observation_accounting_identity')
    if result['state']=='estimated':
        support=observed_rows(result)
        indices=[d['index'] for d in worker.document['dials']]
        expected_support={'schema_version':1,'source_sha256':acquisition['source_sha256'],'pipeline_id':worker.reader.pipeline_id,
                          'reader_observed':support,'document_observed':[support[i] for i in indices],'partial':not all(support)}
        # Missing support/witness is old evidence and must not grant eligibility.
        if 'observation_support' in record:
            check(digest(record['observation_support'])==digest(expected_support),'selector_observation_accounting_support')
    else:support=request['reader_observed']
    binding=db.execute('SELECT source_sha,mask_sha,result_sha,request_sha FROM event_recognition_bindings WHERE event_id=? AND pipeline=? AND context=?',
                       (event,worker.reader.pipeline_id,worker.observation_context)).fetchone()
    reference={'event':acquisition,'pipeline_id':worker.reader.pipeline_id,'format_id':worker.format_id,'context_id':worker.observation_context,
               'request_sha256':request_row[1],'mask_sha256':binding[1],'result_sha256':binding[2],
               'reader_observed':request['reader_observed'],'accounting_segment_id':segment,'accounting_result_sha256':digest(record)}
    if record.get('observation_inference_sha256') is not None:
        check(record['observation_inference_sha256']==digest(result),'selector_observation_inference_changed')
    accepted=(record.get('observation_accepted') is True and record.get('observation_inference_sha256')==digest(result) and
              type(record.get('observation_current_through_us')) is int and
              record['observation_current_through_us']==acquisition['monotonic_us'] and
              record.get('state') in ACCEPTED_STATES and result['state']=='estimated' and
              isinstance(record.get('observation_support'),dict))
    return {'reference':reference,'acquisition':acquisition,'request':request,'result':result,'record':record,'accepted':accepted}

def build(worker,db,event,segment=None):
    if segment is None:
        row=db.execute('SELECT r.segment_id FROM consumption_records r JOIN consumption_segments s ON s.segment_id=r.segment_id '
                       'JOIN consumption_active a ON a.segment_id=s.segment_id WHERE r.event_id=? AND s.format_id=?',(event,worker.format_id)).fetchone()
        if row is None:return None
        segment=row[0]
    row=db.execute('SELECT format_id,first_event,CASE WHEN length(CAST(document AS BLOB))<=? THEN document END FROM consumption_segments WHERE segment_id=?',(MAX_RECORD_BYTES,segment)).fetchone()
    check(row is not None and row[0]==worker.format_id and type(row[1]) is int and row[1]<=event,'selector_observation_segment_invalid')
    document,identity=validate(_decode(row[2],MAX_RECORD_BYTES))
    check(identity==worker.format_id and document==worker.document,'selector_observation_segment_format')
    saved=db.execute('SELECT CASE WHEN length(CAST(result AS BLOB))<=? THEN result END FROM consumption_records WHERE segment_id=? AND event_id=?',(MAX_RECORD_BYTES,segment,event)).fetchone()
    if saved is None:return None
    saved_record=_decode(saved[0],MAX_RECORD_BYTES)
    check(isinstance(saved_record,dict),'selector_observation_accounting_invalid')
    if saved_record.get('observation_context')!=worker.observation_context:return None
    current=_load(worker,db,event,segment)
    record=current['record'];reasons=[]
    if not current['accepted']:reasons.append('accepted_current_observation_missing')
    pair=[]
    for dial in worker.document['dials'][-2:]:
        index=dial['index'];rows=current['result'].get('dial_positions',[])
        item=rows[index] if len(rows)>index else {}
        observed=current['request']['reader_observed'][index]
        position=item.get('position');error=dial['position_error']
        healthy=observed is True and item.get('state')=='estimated' and finite_number(position) and 0<=position<10
        if not healthy:reasons.append('fine_observation_unavailable')
        elif position-error<=0 or position+error>=10:reasons.append('fine_error_interval_wraps')
        pair.append({'index':index,'observed':observed,'state':item.get('state'),'position':position,'position_error':error})
    anchor=None;latest_full=None
    # The producer writes these IDs and an accepted-FULL index atomically with
    # its result. Only constant-count point reads and one indexed LIMIT1 query
    # are used, independent of the retained history length.
    anchor_id=record.get('observation_full_anchor_event_id')
    latest_id=record.get('observation_latest_full_event_id')
    if anchor_id is not None or latest_id is not None:
        check(type(anchor_id) is int and type(latest_id) is int and
              worker.observation_first_event<=row[1]<=anchor_id<=latest_id<=event,'selector_observation_full_ids_invalid')
        latest_index=db.execute('SELECT event_id,CASE WHEN length(result_sha256)=64 THEN result_sha256 END FROM consumption_accepted_full_observations WHERE segment_id=? AND event_id<=? ORDER BY event_id DESC LIMIT 1',(segment,event)).fetchone()
        check(latest_index is not None and latest_index[0]==latest_id,'selector_observation_latest_full_index_invalid')
        for candidate in set((anchor_id,latest_id)):
            item=current if candidate==event else _load(worker,db,candidate,segment)
            indexed=db.execute('SELECT CASE WHEN length(result_sha256)=64 THEN result_sha256 END FROM consumption_accepted_full_observations WHERE segment_id=? AND event_id=?',(segment,candidate)).fetchone()
            check(indexed is not None and indexed[0]==item['reference']['accounting_result_sha256'],'selector_observation_full_index_binding')
            check(item['accepted'] and all(item['request']['reader_observed']),'selector_observation_full_not_accepted')
            if candidate==latest_id:latest_full=item['reference']
            if candidate==anchor_id:
                check(item['record'].get('state')=='anchored' and finite_number(item['record'].get('value')) and
                      item['record']['value']==0 and item['acquisition']['captured_at']==record.get('anchor_captured_at') and
                      item['record'].get('observation_full_anchor_event_id')==candidate,'selector_observation_full_anchor_invalid')
                anchor=item['reference']
    if anchor is None:reasons.append('genuine_full_anchor_missing')
    if latest_full is None:reasons.append('accepted_full_observation_missing')
    for reference in (anchor,latest_full):
        if reference:
            same=reference['event']==current['acquisition'] or capture_clock.interval(reference['event'],current['acquisition'])['state']=='continuous'
            if not same:reasons.append('full_observation_clock_unavailable')
    pair_eligible=not reasons
    unbounded=(record.get('state')=='ambiguous' and record.get('value') is None and record.get('maximum') is None and
               record.get('upper_unbounded') is True and worker.document.get('maximum_rate_per_second') is None)
    uncertain=record.get('state') in ('ambiguous','bounded','unavailable','pending','recovering','rejected','inconsistent')
    return {'schema_version':VERSION,'observation':current['reference'],'accounting_state':record.get('state'),
            'accounting_uncertain':uncertain,'observation_accepted':current['accepted'],'pair':pair,
            'genuine_full_anchor':anchor,'latest_accepted_full_observation':latest_full,
            'fine_observation_eligible':pair_eligible,'relaxation_eligible':pair_eligible and unbounded,
            'reasons':sorted(set(reasons)),'continuity_certified':False,'physical_scalar':None,
            'coarse_information_parity':False}
