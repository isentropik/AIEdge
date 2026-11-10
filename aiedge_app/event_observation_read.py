"""Historical event getter: explicit identity, SQLite read-only, no reader/I/O writes."""
import hashlib,json,re,sqlite3
from pathlib import Path
from recognition import decode_result,MAX_RESULT_BYTES
from reading_format import finite_number
from observation_support import observed_rows

MAX_REQUEST_BYTES=32768
DECISION_REASONS=frozenset(('first','gap','restart','context_changed','quality_uncertain','pose_uncertain',
    'phase_ambiguous','backpressure','partial_recognition_unsupported','periodic_full','observed_motion_probe',
    'phase_uncertainty','requested_cadence_not_supported','missed_prior_recommendation_deadline',
    'fine_observation_uncertain','full_refresh_uncertain','observation_only_unbounded_accounting'))
TIMING_REASONS=frozenset(('capture_clock_missing','capture_clock_anchor_missing','capture_camera_changed',
    'capture_clock_invalid','capture_clock_changed','capture_clock_not_increasing','capture_clock_utc_discontinuity'))
def _check(ok,message):
    if not ok:raise ValueError(message)
def _canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def _digest(value):return hashlib.sha256(_canonical(value).encode()).hexdigest()
def _decode(raw,limit):
    _check(isinstance(raw,str) and len(raw.encode())<=limit,'event_historical_size')
    def pairs(values):
        result={}
        for key,value in values:
            _check(key not in result,'event_historical_duplicate_key');result[key]=value
        return result
    result=json.loads(raw,object_pairs_hook=pairs);_canonical(result);return result
def _evidence(state,request_exists=None,completion_exists=None,completion_valid=False,error=None):
    value=dict(state=state,request_exists=request_exists,completion_exists=completion_exists,completion_valid=completion_valid)
    if error:value['error']=error
    return value

def _public_decision(request,request_sha,result_state):
    """Project validated saved values; never execute policy or expose feedback."""
    def reasons(value):
        _check(isinstance(value,list) and len(value)<=32 and all(type(v) is str and v in DECISION_REASONS for v in value),'event_historical_decision_reasons')
        return list(value)
    mask=request['reader_observed'];mode=request['recommendation']['requested_mode']
    _check(isinstance(mask,list) and 1<=len(mask)<=32 and all(type(v) is bool for v in mask) and any(mask)
        and mode in ('FULL','LAST_TWO') and (all(mask) if mode=='FULL' else sum(mask)==min(2,len(mask))),'event_historical_decision_mask')
    recommendation=request['recommendation'];intervals={}
    for key in ('requested_interval_seconds','supported_interval_seconds'):
        value=recommendation.get(key);_check(finite_number(value) and value>0,'event_historical_decision_interval');intervals[key]=value
    _check(intervals['supported_interval_seconds']>=intervals['requested_interval_seconds'],'event_historical_decision_interval')
    timing=request['timing'];_check(set(timing)=={'state','reason','elapsed_seconds'},'event_historical_decision_timing')
    _check((timing['state']=='continuous' and timing['reason'] is None and finite_number(timing['elapsed_seconds']) and timing['elapsed_seconds']>0)
        or (timing['state']=='unavailable' and type(timing['reason']) is str and timing['reason'] in TIMING_REASONS and timing['elapsed_seconds'] is None),'event_historical_decision_timing')
    _check(type(request['deadline_missed']) is bool and result_state in ('estimated','rejected')
        and isinstance(request_sha,str) and re.fullmatch('[a-f0-9]{64}',request_sha),'event_historical_decision_types')
    return dict(schema_version=1,reader_observed=list(mask),requested_mode=mode,
        reasons=reasons(recommendation.get('reasons')),full_reason=reasons(request['full_reason']),
        timing=dict(timing),deadline_missed=request['deadline_missed'],request_sha256=request_sha,
        result_state=result_state,**intervals)

def _result(state,source,pipeline,error=None,evidence=None):
    value={'state':state,'source_sha256':source,'pipeline_id':pipeline,'accuracy_verified':False,'training_allowed':False}
    if error:value['error']=error
    return {'processed_at':None,'result':value,'decision_evidence':evidence or _evidence(state,error=error)}
def _read(db,event,source,pipeline,context,evidence=None,*,records=None):
    if evidence is None:evidence=_evidence('unavailable')
    row=records['context'] if records is not None else db.execute('SELECT pipeline,format_id,first_event FROM event_selection_contexts WHERE context=?',(context,)).fetchone()
    _check(row is not None and row[0]==pipeline and isinstance(row[1],str) and re.fullmatch('[a-f0-9]{64}',row[1]) and type(row[2]) is int and 1<=row[2]<=event,'event_historical_context')
    format_id=row[1]
    row=records['acquisition'] if records is not None else db.execute('SELECT e.event_id,e.camera,e.frame_id,f.sha256,f.captured_at,c.clock_id,c.monotonic_us FROM capture_events e JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id LEFT JOIN capture_clocks c ON c.camera=e.camera AND c.frame_id=e.frame_id WHERE e.event_id=?',(event,)).fetchone()
    _check(row is not None and row[3]==source,'event_historical_acquisition')
    acquisition=dict(zip(('event_id','camera','frame_id','source_sha256','captured_at','clock_id','monotonic_us'),row))
    row=records['request'] if records is not None else db.execute('SELECT CASE WHEN length(CAST(request AS BLOB))<=? THEN request END,request_sha FROM event_recognition_requests WHERE event_id=? AND pipeline=? AND context=?',(MAX_REQUEST_BYTES,event,pipeline,context)).fetchone()
    evidence.update(request_exists=row is not None)
    if row is None:return _result('pending',source,pipeline,evidence=_evidence('pending',False))
    request=_decode(row[0],MAX_REQUEST_BYTES);request_sha=row[1]
    _check(isinstance(request,dict) and _digest(request)==request_sha,'event_historical_request_hash')
    keys={'reader_observed','recommendation','timing','deadline_missed','flags','full_reason','schema_version','event','pipeline_id','context_id','format_id','configuration','capabilities','feedback','last_full_event'}
    version=request.get('schema_version')
    _check(type(version) is int and version in (1,2) and set(request)==(keys if version==1 else keys|{'observation_eligibility'}),'event_historical_request_schema')
    if version==2:
        eligibility=request['observation_eligibility']
        _check(isinstance(eligibility,dict) and set(eligibility)=={'certificate','certificate_sha256'} and
               _digest(eligibility['certificate'])==eligibility['certificate_sha256'],'event_historical_eligibility_hash')
    _check(request['event']==acquisition and isinstance(request['event'],dict) and all(type(request['event'][k]) is type(v) for k,v in acquisition.items()),'event_historical_acquisition_binding')
    _check(request['pipeline_id']==pipeline and request['context_id']==context and request['format_id']==format_id,'event_historical_request_identity')
    _check(isinstance(request['configuration'],dict) and isinstance(request['capabilities'],dict) and isinstance(request['recommendation'],dict) and isinstance(request['flags'],dict) and isinstance(request['timing'],dict) and isinstance(request['full_reason'],list) and type(request['deadline_missed']) is bool,'event_historical_policy_schema')
    mask=request['reader_observed'];_check(isinstance(mask,list) and 1<=len(mask)<=32 and any(mask) and all(type(x) is bool for x in mask),'event_historical_mask')
    mode=request['recommendation'].get('requested_mode');_check(mode in ('FULL','LAST_TWO') and (all(mask) if mode=='FULL' else sum(mask)==min(2,len(mask))),'event_historical_mode_mask')
    # Preserve historical decisions; never re-run old policy against current code/config.
    mask_sha=_digest(mask)
    binding=records['binding'] if records is not None else db.execute('SELECT source_sha,mask_sha,result_sha,request_sha FROM event_recognition_bindings WHERE event_id=? AND pipeline=? AND context=?',(event,pipeline,context)).fetchone()
    evidence['completion_exists']=binding is not None
    if binding is None:return _result('pending',source,pipeline,evidence=_evidence('pending',True,False))
    _check(binding[0]==source and binding[1]==mask_sha and binding[3]==request_sha,'event_historical_completion_binding')
    cache=records['cache'] if records is not None else db.execute('SELECT CASE WHEN length(CAST(mask AS BLOB))<=? THEN mask END,CASE WHEN length(CAST(result AS BLOB))<=? THEN result END,result_sha FROM event_recognition_cache WHERE source_sha=? AND pipeline=? AND mask_sha=?',(MAX_REQUEST_BYTES,MAX_RESULT_BYTES,source,pipeline,mask_sha)).fetchone()
    _check(cache is not None,'event_historical_cache_missing')
    stored_mask=_decode(cache[0],MAX_REQUEST_BYTES)
    _check(stored_mask==mask and isinstance(stored_mask,list) and all(type(x) is bool for x in stored_mask) and _digest(stored_mask)==mask_sha,'event_historical_cache_mask')
    result=_decode(cache[1],MAX_RESULT_BYTES);_check(isinstance(result,dict) and _digest(result)==cache[2]==binding[2],'event_historical_cache_hash')
    decode_result(cache[1],source,pipeline);_check('event_observation' not in result,'event_historical_cache_contains_event')
    if result['state']=='estimated':
        rows=result.get('dial_positions');_check(isinstance(rows,list) and len(rows)==len(mask) and observed_rows(result)==mask,'event_historical_support')
        for item,flag in zip(rows,mask):
            if flag:_check(item.get('state')=='estimated' and finite_number(item.get('position')) and 0<=item['position']<10,'event_historical_position')
            else:_check(item.get('state')=='unavailable' and item.get('position') is None and 'scores_sha256' not in item,'event_historical_unobserved_stale')
    elif not all(mask):
        a=result.get('observation_attempt');_check(isinstance(a,dict) and a.get('requested_observed')==mask and a.get('source_sha256')==source and a.get('pipeline_id')==pipeline,'event_historical_attempt')
    observation={k:acquisition[k] for k in ('event_id','camera','captured_at','clock_id','monotonic_us','source_sha256')}
    observation.update(context_id=context,format_id=format_id,request_sha256=request_sha)
    evidence['completion_valid']=True
    value={'processed_at':None,'result':{**result,'event_observation':observation}}
    try:
        decision=_public_decision(request,request_sha,result['state'])
    except (ValueError,TypeError,KeyError,AttributeError,IndexError,RecursionError,OverflowError):
        value['decision_evidence']=_evidence('unavailable',True,True,True,'event_historical_decision_summary_invalid')
    else:
        value.update(decision=decision,decision_evidence=_evidence('complete',True,True,True))
    return value
def read_batch(db, sources, pipeline):
    """One bounded SELECT; release its cursor before validating saved evidence.

    Uses the same validator as single-event reads. No transaction spans batches,
    no persistent cache, no weakened hash/mask/acquisition checks.
    """
    if not sources or len(sources)>64:raise ValueError('historical batch size')
    wanted=[(s['event_id'],s['context_id']) for s in sources]
    if len(set(wanted))!=len(wanted):raise ValueError('duplicate historical batch')
    sql='''WITH wanted(event,context) AS (VALUES %s)
      SELECT w.event,w.context,x.pipeline,x.format_id,x.first_event,
       e.event_id,e.camera,e.frame_id,f.sha256,f.captured_at,c.clock_id,c.monotonic_us,
       r.event_id,CASE WHEN length(CAST(r.request AS BLOB))<=32768 THEN r.request END,r.request_sha,
       b.event_id,b.source_sha,b.mask_sha,b.result_sha,b.request_sha,
       k.source_sha,CASE WHEN length(CAST(k.mask AS BLOB))<=32768 THEN k.mask END,
       CASE WHEN length(CAST(k.result AS BLOB))<=? THEN k.result END,k.result_sha
      FROM wanted w
      LEFT JOIN event_selection_contexts x ON x.context=w.context
      LEFT JOIN capture_events e ON e.event_id=w.event
      LEFT JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id
      LEFT JOIN capture_clocks c ON c.camera=e.camera AND c.frame_id=e.frame_id
      LEFT JOIN event_recognition_requests r ON r.event_id=w.event AND r.context=w.context AND r.pipeline=?
      LEFT JOIN event_recognition_bindings b ON b.event_id=w.event AND b.context=w.context AND b.pipeline=?
      LEFT JOIN event_recognition_cache k ON k.source_sha=b.source_sha AND k.mask_sha=b.mask_sha AND k.pipeline=?
    ''' % ','.join('(?,?)' for _ in wanted)
    params=[v for pair in wanted for v in pair]+[MAX_RESULT_BYTES,pipeline,pipeline,pipeline]
    rows=db.execute(sql,params).fetchall()
    if len(rows)!=len(wanted):raise ValueError('ambiguous historical batch')
    bound={(r[0],r[1]):dict(context=r[2:5] if r[2] is not None else None,
        acquisition=r[5:12] if r[5] is not None else None,
        request=r[13:15] if r[12] is not None else None,
        binding=r[16:20] if r[15] is not None else None,
        cache=r[21:24] if r[20] is not None else None) for r in rows}
    return [_read(db,s['event_id'],s['source_sha256'],pipeline,s['context_id'],{},
                  records=bound[(s['event_id'],s['context_id'])]) for s in sources]

def read_event(store,event,digest,pipeline,context):
    """Returns unavailable on invalid identity/evidence; never legacy digest fallback."""
    evidence=_evidence('unavailable')
    try:
        _check(type(event) is int and event>=1 and isinstance(digest,str) and re.fullmatch('[a-f0-9]{64}',digest),'event_historical_identity')
        _check(isinstance(pipeline,str) and re.fullmatch('[A-Za-z0-9_.-]{1,128}',pipeline) and isinstance(context,str) and re.fullmatch('[a-f0-9]{64}',context),'event_historical_identity')
        uri=(Path(store.root)/'captures.sqlite3').resolve().as_uri()+'?mode=ro'
        db=sqlite3.connect(uri,uri=True,timeout=10)
        try:
            db.execute('BEGIN')
            return _read(db,event,digest,pipeline,context,evidence)
        finally:db.close()
    except (ValueError,TypeError,KeyError,AttributeError,IndexError,RecursionError,OverflowError):
        evidence.update(state='unavailable',completion_valid=False,error='event_historical_binding_invalid')
        return _result('unavailable',digest,pipeline,'event_historical_binding_invalid',evidence)
    except (OSError,sqlite3.Error):
        evidence.update(state='unavailable',completion_valid=False,error='event_historical_storage_unavailable')
        return _result('unavailable',digest,pipeline,'event_historical_storage_unavailable',evidence)
