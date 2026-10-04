"""Historical event getter: explicit identity, SQLite read-only, no reader/I/O writes."""
import hashlib,json,re,sqlite3
from pathlib import Path
from recognition import decode_result,MAX_RESULT_BYTES
from reading_format import finite_number
from observation_support import observed_rows

MAX_REQUEST_BYTES=32768
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
def _result(state,source,pipeline,error=None):
    value={'state':state,'source_sha256':source,'pipeline_id':pipeline,'accuracy_verified':False,'training_allowed':False}
    if error:value['error']=error
    return {'processed_at':None,'result':value}
def _read(db,event,source,pipeline,context):
    row=db.execute('SELECT pipeline,format_id,first_event FROM event_selection_contexts WHERE context=?',(context,)).fetchone()
    _check(row is not None and row[0]==pipeline and isinstance(row[1],str) and re.fullmatch('[a-f0-9]{64}',row[1]) and type(row[2]) is int and 1<=row[2]<=event,'event_historical_context')
    format_id=row[1]
    row=db.execute('SELECT e.event_id,e.camera,e.frame_id,f.sha256,f.captured_at,c.clock_id,c.monotonic_us FROM capture_events e JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id LEFT JOIN capture_clocks c ON c.camera=e.camera AND c.frame_id=e.frame_id WHERE e.event_id=?',(event,)).fetchone()
    _check(row is not None and row[3]==source,'event_historical_acquisition')
    acquisition=dict(zip(('event_id','camera','frame_id','source_sha256','captured_at','clock_id','monotonic_us'),row))
    row=db.execute('SELECT CASE WHEN length(CAST(request AS BLOB))<=? THEN request END,request_sha FROM event_recognition_requests WHERE event_id=? AND pipeline=? AND context=?',(MAX_REQUEST_BYTES,event,pipeline,context)).fetchone()
    if row is None:return _result('pending',source,pipeline)
    request=_decode(row[0],MAX_REQUEST_BYTES);request_sha=row[1]
    _check(isinstance(request,dict) and _digest(request)==request_sha,'event_historical_request_hash')
    keys={'reader_observed','recommendation','timing','deadline_missed','flags','full_reason','schema_version','event','pipeline_id','context_id','format_id','configuration','capabilities','feedback','last_full_event'}
    _check(set(request)==keys and type(request['schema_version']) is int and request['schema_version']==1,'event_historical_request_schema')
    _check(request['event']==acquisition and isinstance(request['event'],dict) and all(type(request['event'][k]) is type(v) for k,v in acquisition.items()),'event_historical_acquisition_binding')
    _check(request['pipeline_id']==pipeline and request['context_id']==context and request['format_id']==format_id,'event_historical_request_identity')
    _check(isinstance(request['configuration'],dict) and isinstance(request['capabilities'],dict) and isinstance(request['recommendation'],dict) and isinstance(request['flags'],dict) and isinstance(request['timing'],dict) and isinstance(request['full_reason'],list) and type(request['deadline_missed']) is bool,'event_historical_policy_schema')
    mask=request['reader_observed'];_check(isinstance(mask,list) and 1<=len(mask)<=32 and any(mask) and all(type(x) is bool for x in mask),'event_historical_mask')
    mode=request['recommendation'].get('requested_mode');_check(mode in ('FULL','LAST_TWO') and (all(mask) if mode=='FULL' else sum(mask)==min(2,len(mask))),'event_historical_mode_mask')
    # Preserve historical decisions; never re-run old policy against current code/config.
    mask_sha=_digest(mask)
    binding=db.execute('SELECT source_sha,mask_sha,result_sha,request_sha FROM event_recognition_bindings WHERE event_id=? AND pipeline=? AND context=?',(event,pipeline,context)).fetchone()
    if binding is None:return _result('pending',source,pipeline)
    _check(binding[0]==source and binding[1]==mask_sha and binding[3]==request_sha,'event_historical_completion_binding')
    cache=db.execute('SELECT CASE WHEN length(CAST(mask AS BLOB))<=? THEN mask END,CASE WHEN length(CAST(result AS BLOB))<=? THEN result END,result_sha FROM event_recognition_cache WHERE source_sha=? AND pipeline=? AND mask_sha=?',(MAX_REQUEST_BYTES,MAX_RESULT_BYTES,source,pipeline,mask_sha)).fetchone()
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
    return {'processed_at':None,'result':{**result,'event_observation':observation}}
def read_event(store,event,digest,pipeline,context):
    """Returns unavailable on invalid identity/evidence; never legacy digest fallback."""
    try:
        _check(type(event) is int and event>=1 and isinstance(digest,str) and re.fullmatch('[a-f0-9]{64}',digest),'event_historical_identity')
        _check(isinstance(pipeline,str) and re.fullmatch('[A-Za-z0-9_.-]{1,128}',pipeline) and isinstance(context,str) and re.fullmatch('[a-f0-9]{64}',context),'event_historical_identity')
        uri=(Path(store.root)/'captures.sqlite3').resolve().as_uri()+'?mode=ro'
        db=sqlite3.connect(uri,uri=True,timeout=10)
        try:
            db.execute('BEGIN')
            return _read(db,event,digest,pipeline,context)
        finally:db.close()
    except (ValueError,TypeError,KeyError,AttributeError,IndexError,RecursionError,OverflowError):
        return _result('unavailable',digest,pipeline,'event_historical_binding_invalid')
    except (OSError,sqlite3.Error):
        return _result('unavailable',digest,pipeline,'event_historical_storage_unavailable')
