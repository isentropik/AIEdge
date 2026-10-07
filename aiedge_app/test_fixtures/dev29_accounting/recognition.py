"""Durable, deduplicated inference on immutable captures. Results are never labels."""
import json,re,sqlite3,threading,time
from capture import now
from observation_support import observed_rows

MAX_RESULT_BYTES=262144

def decode_result(encoded,digest,pipeline):
    value=json.loads(encoded)
    json.dumps(value,allow_nan=False)
    if not isinstance(value,dict) or value.get('state') not in ('estimated','rejected') or value.get('pipeline_id')!=pipeline or value.get('source_sha256')!=digest:
        raise ValueError('invalid_stored_result')
    if value.get('training_allowed') is not False or value.get('accuracy_verified') is not False:
        raise ValueError('invalid_result_provenance')
    rows=value.get('dial_positions',[])
    if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):raise ValueError('invalid_dial_results')
    if 'observation_attempt' in value:
        attempt=value['observation_attempt']
        if value['state']!='rejected' or not isinstance(attempt,dict) or set(attempt)!={'schema_version','source_sha256','pipeline_id','requested_observed'}:
            raise ValueError('invalid_observation_attempt')
        if type(attempt['schema_version']) is not int or attempt['schema_version']!=1 or attempt['source_sha256']!=digest or attempt['pipeline_id']!=pipeline:
            raise ValueError('invalid_observation_attempt_identity')
        mask=attempt['requested_observed']
        if not isinstance(mask,list) or not 1<=len(mask)<=32 or any(type(flag) is not bool for flag in mask) or not any(mask):
            raise ValueError('invalid_observation_attempt_mask')
    if 'observation_support' in value:observed_rows(value)
    return value

class Recognition:
    def __init__(self,store,reader=None):
        self.store,self.reader=store,reader
        self.stop=threading.Event();self.lock=threading.Lock();self.last_error=None
        with store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS inference (sha256 TEXT NOT NULL,pipeline TEXT NOT NULL,processed_at TEXT NOT NULL,result TEXT NOT NULL,PRIMARY KEY(sha256,pipeline))')
    def activate(self,reader,persist):
        # Finish any current frame before switching; failed persistence leaves it active.
        with self.lock:
            persist()
            self.reader=reader
    def once(self):
        # Give the current capture priority, then drain history oldest first.
        # A completed rejection is evidence and is not retried forever.
        with self.lock:
            if self.reader is None:return False
            with self.store.connect() as db:
                row=db.execute('SELECT f.sha256 FROM capture_events e JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id WHERE NOT EXISTS (SELECT 1 FROM inference i WHERE i.sha256=f.sha256 AND i.pipeline=?) ORDER BY (e.event_id=(SELECT MAX(event_id) FROM capture_events)) DESC,e.event_id LIMIT 1',(self.reader.pipeline_id,)).fetchone()
            if not row:return False
            self.store.performance.begin_recognition(row[0])
            with self.store.performance.measure('recognition') as sample:
                state=self._process(row[0])
                sample.outcome='success' if state=='estimated' else 'rejected'
            return True
    def _process(self,digest):
        start=time.perf_counter()
        try:
            with self.store.performance.measure('read_and_infer'):
                result=self.reader.read_jpeg(self.store.image(digest))
            if result.get('pipeline_id',self.reader.pipeline_id)!=self.reader.pipeline_id:
                raise ValueError('reader_pipeline_mismatch')
        except Exception as exc:
            result={'state':'rejected','error':str(exc) if isinstance(exc,ValueError) else type(exc).__name__,
                    'dial_positions':[],'physical_value':None}
        result.update(source_sha256=digest,pipeline_id=self.reader.pipeline_id,training_allowed=False,accuracy_verified=False)
        result['total_processing_seconds']=time.perf_counter()-start
        encoded=json.dumps(result,allow_nan=False)
        with self.store.performance.measure('inference_commit'),self.store.connect() as db:
            db.execute('INSERT INTO inference VALUES(?,?,?,?)',(digest,self.reader.pipeline_id,now(),encoded))
        return result['state']
    def latest(self):
        # Snapshot the active pipeline while holding the same lock as activation.
        with self.lock:
            if self.reader is None:return {'state':'not_configured'}
            pipeline=self.reader.pipeline_id
        with self.store.connect() as db:
            row=db.execute('SELECT f.sha256 FROM capture_events e JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id ORDER BY e.event_id DESC LIMIT 1').fetchone()
            if not row:return {'state':'waiting_for_image'}
        return self.stored(row[0],pipeline)['result']
    def stored(self,digest,pipeline):
        """Read an existing result under its original pipeline; never run a model.

        A trial can outlive the active reader and browser. Keep historical results
        addressable without relabelling them as current or replacing rejected ones.
        """
        if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('invalid_result_identity')
        if not isinstance(pipeline,str) or not re.fullmatch('[A-Za-z0-9_.-]{1,128}',pipeline):raise ValueError('invalid_result_identity')
        with self.store.connect() as db:
            row=db.execute('SELECT processed_at,CASE WHEN length(CAST(result AS BLOB))<=? THEN result ELSE NULL END FROM inference WHERE sha256=? AND pipeline=?',
                           (MAX_RESULT_BYTES,digest,pipeline)).fetchone()
        identity=dict(source_sha256=digest,pipeline_id=pipeline,training_allowed=False,accuracy_verified=False)
        if not row:return {'processed_at':None,'result':dict(identity,state='pending')}
        try:
            result=decode_result(row[1],digest,pipeline)
            from datetime import datetime
            if not isinstance(row[0],str):raise ValueError('invalid_processed_time')
            stamp=datetime.fromisoformat(row[0].replace('Z','+00:00'))
            if stamp.tzinfo is None or stamp.year<2020:raise ValueError('invalid_processed_time')
            return {'processed_at':row[0],'result':result}
        except (ValueError,TypeError,RecursionError):
            # Preserve the evidence; never substitute a previous image's result.
            return {'processed_at':None,'result':dict(identity,state='unavailable',error='stored_result_invalid')}
    def run(self):
        while not self.stop.is_set():
            try:
                worked=self.once();self.last_error=None
                if not worked:self.stop.wait(1)
            except (OSError,sqlite3.Error):
                self.last_error='recognition_storage_unavailable';self.stop.wait(5)
