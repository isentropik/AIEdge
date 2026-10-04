"""Explicit opt-in event recognition; default Recognition/service remain unchanged."""
import hashlib,json,sqlite3
import capture_clock
from pathlib import Path
from recognition import Recognition,decode_result,MAX_RESULT_BYTES
from reading_format import validate,finite_number
from observation_support import observed_rows
from event_selection import encoded,digest,decide
from wheel_capture_policy import recommend
from capture import now
from event_observation_read import read_event

MAX_REQUEST_BYTES=32768
def check(ok,reason):
    if not ok:raise ValueError(reason)
def decode(raw,limit=MAX_RESULT_BYTES):
    check(isinstance(raw,str) and len(raw.encode())<=limit,'event_saved_size')
    def pairs(values):
        result={}
        for k,v in values:
            check(k not in result,'event_duplicate_json_key');result[k]=v
        return result
    value=json.loads(raw,object_pairs_hook=pairs);encoded(value);return value

class EventRecognition(Recognition):
    def __init__(self,store,reader,document,configuration,capabilities):
        super().__init__(store,reader)
        self.document,self.format_id=validate(document)
        self.observation_format_id=self.format_id
        check(reader is not None and self.document['pipeline_id']==reader.pipeline_id,'event_pipeline_mismatch')
        check(len(self.document['dials'])==len(reader.dials) and sorted(d['index'] for d in self.document['dials'])==list(range(len(reader.dials))),'event_dial_mapping')
        recommend({'first':True},capabilities,configuration)
        self.configuration=decode(encoded(configuration));self.capabilities=decode(encoded(capabilities))
        deps=['event_recognition.py','event_selection.py','event_observation_read.py','wheel_capture_policy.py','reader.py','recognition.py','observation_support.py','consumption.py','accounting_native.py','capture_clock.py','reading_format.py']
        self.observation_context=digest({'version':1,'format_id':self.format_id,'pipeline':reader.pipeline_id,'document':self.document,'configuration':self.configuration,'capabilities':self.capabilities,
                                         'sources':{n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in deps}})
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS event_selection_contexts(context TEXT PRIMARY KEY,pipeline TEXT NOT NULL,format_id TEXT NOT NULL,first_event INTEGER NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS event_recognition_requests(event_id INTEGER NOT NULL,pipeline TEXT NOT NULL,context TEXT NOT NULL,request TEXT NOT NULL,request_sha TEXT NOT NULL,PRIMARY KEY(event_id,pipeline,context))')
            db.execute('CREATE TABLE IF NOT EXISTS event_recognition_cache(source_sha TEXT NOT NULL,pipeline TEXT NOT NULL,mask_sha TEXT NOT NULL,mask TEXT NOT NULL,result TEXT NOT NULL,result_sha TEXT NOT NULL,PRIMARY KEY(source_sha,pipeline,mask_sha))')
            db.execute('CREATE TABLE IF NOT EXISTS event_recognition_bindings(event_id INTEGER NOT NULL,pipeline TEXT NOT NULL,context TEXT NOT NULL,source_sha TEXT NOT NULL,mask_sha TEXT NOT NULL,result_sha TEXT NOT NULL,request_sha TEXT NOT NULL,PRIMARY KEY(event_id,pipeline,context))')
            row=db.execute('SELECT pipeline,format_id,first_event FROM event_selection_contexts WHERE context=?',(self.observation_context,)).fetchone()
            if row:
                latest=max(1,db.execute('SELECT COALESCE(MAX(event_id),0) FROM capture_events').fetchone()[0])
                check(row[:2]==(reader.pipeline_id,self.format_id) and type(row[2]) is int and 1<=row[2]<=latest,'event_context_saved_invalid');self.observation_first_event=row[2]
            else:
                self.observation_first_event=max(1,db.execute('SELECT COALESCE(MAX(event_id),0) FROM capture_events').fetchone()[0])
                db.execute('INSERT INTO event_selection_contexts VALUES(?,?,?,?)',(self.observation_context,reader.pipeline_id,self.format_id,self.observation_first_event))
        self._restart_pending=bool(row)
    def activate(self,reader,persist):
        check(reader is not None and reader.pipeline_id==self.reader.pipeline_id and len(reader.dials)==len(self.document['dials']),'event_reconfigure_requires_new_context')
        return super().activate(reader,persist)
    def stored_event(self,event,digest,pipeline,context=None):
        return read_event(self.store,event,digest,pipeline,self.observation_context if context is None else context)
    def latest(self):
        with self.lock:pipeline=self.reader.pipeline_id
        with self.store.connect() as db:
            event=db.execute('SELECT MAX(event_id) FROM capture_events').fetchone()[0]
            current=self._event(db,event) if event is not None else None
        if current is None:return {'state':'waiting_for_image'}
        try:return self.event_result(event,current['source_sha256'],pipeline)
        except (ValueError,TypeError,KeyError,RecursionError):return {'state':'unavailable','error':'event_recognition_saved_state_invalid'}
        except (OSError,sqlite3.Error):return {'state':'unavailable','error':'event_recognition_storage_unavailable'}
    @staticmethod
    def _event(db,event):
        row=db.execute('SELECT e.event_id,e.camera,e.frame_id,f.sha256,f.captured_at,c.clock_id,c.monotonic_us FROM capture_events e JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id LEFT JOIN capture_clocks c ON c.camera=e.camera AND c.frame_id=e.frame_id WHERE e.event_id=?',(event,)).fetchone()
        return dict(zip(('event_id','camera','frame_id','source_sha256','captured_at','clock_id','monotonic_us'),row)) if row else None
    def _request(self,db,event):
        try:return self._validated_request(db,event)
        except (KeyError,TypeError,IndexError,AttributeError,OverflowError) as exc:raise ValueError('event_request_malformed') from exc
    def _validated_request(self,db,event):
        row=db.execute('SELECT request,request_sha FROM event_recognition_requests WHERE event_id=? AND pipeline=? AND context=?',(event,self.reader.pipeline_id,self.observation_context)).fetchone()
        if row is None:return None
        r=decode(row[0],MAX_REQUEST_BYTES);check(digest(r)==row[1],'event_request_tampered')
        required={'reader_observed','recommendation','timing','deadline_missed','flags','full_reason','schema_version','event','pipeline_id','context_id','format_id','configuration','capabilities','feedback','last_full_event'}
        check(isinstance(r,dict) and set(r)==required,'event_request_keys_invalid')
        actual_event=self._event(db,event)
        check(isinstance(r['event'],dict) and r['event']==actual_event and all(type(r['event'][k]) is type(v) for k,v in actual_event.items()) and r['pipeline_id']==self.reader.pipeline_id and r['context_id']==self.observation_context and r['format_id']==self.format_id,'event_request_binding_invalid')
        check(type(r['deadline_missed']) is bool and (r['last_full_event'] is None or (type(r['last_full_event']) is int and self.observation_first_event<=r['last_full_event']<event)),'event_request_flags_invalid')
        mask=r['reader_observed'];check(isinstance(mask,list) and len(mask)==len(self.reader.dials) and any(mask) and all(type(f) is bool for f in mask),'event_request_mask_invalid')
        check(r['configuration']==self.configuration and r['capabilities']==self.capabilities,'event_request_policy_drift')
        check(type(r['schema_version']) is int and r['schema_version']==1 and recommend(r['flags'],self.capabilities,self.configuration)==r['recommendation'],'event_request_recommendation_invalid')
        check(r['flags'].get('first') is (r['last_full_event'] is None),'event_request_anchor_flag_invalid')
        desired=[True]*len(mask)
        if r['recommendation']['requested_mode']=='LAST_TWO':
            desired=[False]*len(mask)
            for dial in self.document['dials'][-2:]:desired[dial['index']]=True
        check(mask==desired,'event_request_decision_mask_invalid')
        feedback=r.get('feedback')
        check(feedback is None or (isinstance(feedback,dict) and set(feedback)=={'segment_id','event_id','result_sha256','genuine_full_anchor','result'} and type(feedback['event_id']) is int and self.observation_first_event<=feedback['event_id']<event and type(feedback['genuine_full_anchor']) is bool),'event_request_feedback_invalid')
        if feedback:
            prior=db.execute('SELECT result FROM consumption_records WHERE segment_id=? AND event_id=?',(feedback['segment_id'],feedback['event_id'])).fetchone()
            check(prior is not None,'event_request_feedback_missing')
            saved=decode(prior[0]);check(isinstance(saved,dict) and digest(saved)==feedback['result_sha256'],'event_request_feedback_changed')
            check(feedback['result']=={k:saved[k] for k in ('state','event_id','segment_id','source_sha256','format_id','observation_context')},'event_request_feedback_summary_invalid')
        return r
    def _cache(self,db,source,mask):
        row=db.execute('SELECT mask,result,result_sha FROM event_recognition_cache WHERE source_sha=? AND pipeline=? AND mask_sha=?',(source,self.reader.pipeline_id,digest(mask))).fetchone()
        if row is None:return None
        cached_mask=decode(row[0]);check(cached_mask==mask and isinstance(cached_mask,list) and all(type(x) is bool for x in cached_mask) and digest(cached_mask)==digest(mask),'event_cache_mask_invalid');r=decode(row[1]);check(digest(r)==row[2],'event_cache_tampered')
        decode_result(row[1],source,self.reader.pipeline_id)
        if r['state']=='estimated':
            check(len(r.get('dial_positions',[]))==len(mask),'event_cache_dial_count')
            check(observed_rows(r)==mask,'event_cache_support_invalid')
            for item,flag in zip(r['dial_positions'],mask):
                if flag:check(item.get('state')=='estimated' and finite_number(item.get('position')) and 0<=item['position']<10,'event_cache_position_invalid')
        elif not all(mask):
            a=r.get('observation_attempt');check(isinstance(a,dict) and a.get('requested_observed')==mask and a.get('source_sha256')==source and a.get('pipeline_id')==self.reader.pipeline_id,'event_cache_attempt_invalid')
        return r
    def accounting_result(self,event,digest_value,pipeline):
        # Consumption holds Recognition.lock: this getter MUST NOT acquire it.
        check(pipeline==self.reader.pipeline_id,'event_getter_pipeline_mismatch')
        with self.store.connect() as db:
            r=self._request(db,event)
            if r is None:return None
            check(r['event']['source_sha256']==digest_value,'event_getter_digest_mismatch')
            binding=db.execute('SELECT source_sha,mask_sha,result_sha,request_sha FROM event_recognition_bindings WHERE event_id=? AND pipeline=? AND context=?',(event,pipeline,self.observation_context)).fetchone()
            if not binding:return None
            check(binding[0]==digest_value and binding[1]==digest(r['reader_observed']) and binding[3]==digest(r),'event_completed_binding_invalid')
            result=self._cache(db,digest_value,r['reader_observed']);check(result is not None and digest(result)==binding[2],'event_completed_cache_missing')
            result={**result,'event_observation':{**{k:r['event'][k] for k in ('event_id','camera','captured_at','clock_id','monotonic_us','source_sha256')},'context_id':self.observation_context,'format_id':self.format_id,'request_sha256':digest(r)}}
            return encoded(result)
    def event_result(self,event,digest_value,pipeline):
        value=self.accounting_result(event,digest_value,pipeline);return decode(value) if value is not None else {'state':'pending'}
    def _feedback(self,db,event):
        try:
            row=db.execute('SELECT r.segment_id,r.result FROM consumption_records r JOIN consumption_segments s ON s.segment_id=r.segment_id JOIN consumption_active a ON a.segment_id=s.segment_id WHERE r.event_id=? AND s.format_id=?',(event,self.format_id)).fetchone()
        except sqlite3.OperationalError as exc:
            if str(exc).startswith('no such table: consumption_'):return None
            raise
        if not row:return None
        value=decode(row[1]);check(isinstance(value,dict),'event_feedback_malformed');check(value.get('event_id')==event and value.get('format_id')==self.format_id,'event_feedback_binding_invalid')
        if value.get('observation_context')!=self.observation_context:return None
        request=self._request(db,event)
        check(request is not None and value.get('segment_id')==row[0] and value.get('source_sha256')==request['event']['source_sha256'],'event_feedback_source_invalid')
        expected={**{k:request['event'][k] for k in ('event_id','camera','captured_at','clock_id','monotonic_us','source_sha256')},'context_id':self.observation_context,'format_id':self.format_id,'request_sha256':digest(request)}
        check(value.get('event_observation')==expected,'event_feedback_observation_invalid')
        anchor=value.get('anchor_captured_at');genuine=False
        if isinstance(anchor,str):
            candidates=db.execute('SELECT e.event_id FROM capture_events e JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id WHERE e.event_id<=? AND f.captured_at=? ORDER BY e.event_id DESC LIMIT 128',(event,anchor)).fetchall()
            for candidate in candidates:
                anchor_request=self._request(db,candidate[0])
                anchor_feedback=db.execute('SELECT result FROM consumption_records WHERE segment_id=? AND event_id=?',(row[0],candidate[0])).fetchone()
                if anchor_request and all(anchor_request['reader_observed']) and anchor_feedback:
                    av=decode(anchor_feedback[0]);check(isinstance(av,dict),'event_anchor_feedback_malformed')
                    binding=av.get('event_observation');check(isinstance(binding,dict),'event_anchor_feedback_malformed')
                    genuine=av.get('state')=='anchored' and av.get('observation_context')==self.observation_context and binding.get('request_sha256')==digest(anchor_request)
                    if genuine:break
        return {'segment_id':row[0],'event_id':event,'result_sha256':digest(value),'genuine_full_anchor':genuine,'result':{k:value[k] for k in ('state','event_id','segment_id','source_sha256','format_id','observation_context')}}
    def _speed(self,db,event):
        rows=db.execute('SELECT event_id FROM event_recognition_bindings WHERE pipeline=? AND context=? AND event_id<=? ORDER BY event_id DESC LIMIT 2',(self.reader.pipeline_id,self.observation_context,event)).fetchall()
        if len(rows)!=2:return None
        newer,older=[self._request(db,r[0]) for r in rows];timing=capture_clock.interval(older['event'],newer['event'])
        if timing['state']!='continuous':return None
        finest=self.document['dials'][-1]['index']
        values=[]
        for request in (older,newer):
            if not request['reader_observed'][finest]:return None
            result=self._cache(db,request['event']['source_sha256'],request['reader_observed'])
            if result is None or result['state']!='estimated':return None
            values.append(result['dial_positions'][finest]['position'])
        difference=abs(values[1]-values[0])%10
        return min(difference,10-difference)/timing['elapsed_seconds']
    def once(self):
        with self.store.performance.measure('recognition') as sample:
            worked=self._once();sample.outcome='success' if worked and getattr(self,'_last_state',None)=='estimated' else 'rejected'
            return worked
    def _once(self):
        with self.lock:
            pipeline=self.reader.pipeline_id;context=self.observation_context
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT e.event_id FROM capture_events e WHERE e.event_id>=? AND NOT EXISTS(SELECT 1 FROM event_recognition_bindings b WHERE b.event_id=e.event_id AND b.pipeline=? AND b.context=?) ORDER BY e.event_id LIMIT 1',(self.observation_first_event,pipeline,context)).fetchone()
                if not row:return False
                event=row[0];request=self._request(db,event)
                if request is None:
                    current=self._event(db,event)
                    prior=db.execute('SELECT event_id FROM event_recognition_bindings WHERE pipeline=? AND context=? AND event_id<? ORDER BY event_id DESC LIMIT 1',(pipeline,context,event)).fetchone()
                    feedback=self._feedback(db,prior[0]) if prior else None
                    if prior and feedback is None:return False
                    previous_request=self._request(db,prior[0]) if prior else None;previous=previous_request['event'] if previous_request else None
                    last_full_id=previous_request.get('last_full_event') if previous_request else None
                    if feedback and not feedback['genuine_full_anchor']:last_full_id=None
                    if prior and feedback['genuine_full_anchor'] and all(previous_request['reader_observed']) and feedback['result'].get('state') in ('anchored','estimated','within_noise','bounded','ambiguous'):last_full_id=prior[0]
                    last_full=self._event(db,last_full_id) if last_full_id else None
                    decision=decide(current,previous,previous_request,feedback['result'] if feedback else None,last_full,self._restart_pending,self.document,self.configuration,self.capabilities,observed_phase_speed=self._speed(db,prior[0]) if prior else None)
                    request={**decision,'schema_version':1,'event':current,'pipeline_id':pipeline,'context_id':context,'format_id':self.format_id,'configuration':self.configuration,'capabilities':self.capabilities,'feedback':feedback,'last_full_event':last_full_id}
                    encoded_request=encoded(request);check(len(encoded_request.encode())<=MAX_REQUEST_BYTES,'event_request_too_large')
                    db.execute('INSERT INTO event_recognition_requests VALUES(?,?,?,?,?)',(event,pipeline,context,encoded_request,digest(request)))
                    self._restart_pending=False
            # Request transaction closed and durable BEFORE source image or model call.
            mask=request['reader_observed'];source=request['event']['source_sha256']
            with self.store.connect() as db:result=self._cache(db,source,mask)
            if result is None:
                try:
                    with self.store.performance.measure('read_and_infer'):
                        result=self.reader.read_jpeg(self.store.image(source)) if all(mask) else self.reader.read_jpeg(self.store.image(source),observed=mask)
                except Exception as exc:
                    result={'state':'rejected','error':str(exc) if isinstance(exc,ValueError) else type(exc).__name__,'dial_positions':[]}
                    if not all(mask):result['observation_attempt']={'schema_version':1,'source_sha256':source,'pipeline_id':pipeline,'requested_observed':mask}
                check(result.get('pipeline_id',pipeline)==pipeline and result.get('source_sha256',source)==source,'event_reader_identity_mismatch')
                result.update(source_sha256=source,pipeline_id=pipeline,training_allowed=False,accuracy_verified=False)
                raw=encoded(result);check(len(raw.encode())<=MAX_RESULT_BYTES,'event_result_too_large');decode_result(raw,source,pipeline)
                with self.store.performance.measure('inference_commit'),self.store.connect() as db:
                    db.execute('INSERT OR IGNORE INTO event_recognition_cache VALUES(?,?,?,?,?,?)',(source,pipeline,digest(mask),encoded(mask),raw,digest(result)))
                    result=self._cache(db,source,mask)
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE');saved=self._request(db,event);check(saved==request,'event_request_changed_during_inference')
                binding=(event,pipeline,context,source,digest(mask),digest(result),digest(request))
                db.execute('INSERT OR IGNORE INTO event_recognition_bindings VALUES(?,?,?,?,?,?,?)',binding)
                actual=db.execute('SELECT event_id,pipeline,context,source_sha,mask_sha,result_sha,request_sha FROM event_recognition_bindings WHERE event_id=? AND pipeline=? AND context=?',(event,pipeline,context)).fetchone()
                check(actual==binding,'event_binding_race_invalid')
            self._last_state=result['state']
            return True
    def run(self):
        blocked=False
        while not self.stop.is_set():
            if blocked:self.stop.wait(5);continue
            try:
                if not self.once():self.stop.wait(.5)
                self.last_error=None
            except (ValueError,TypeError,KeyError,RecursionError):
                self.last_error='event_recognition_saved_state_invalid';blocked=True
            except (OSError,sqlite3.Error):
                self.last_error='event_recognition_storage_unavailable';self.stop.wait(5)
