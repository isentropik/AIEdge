"""Durable, deduplicated inference on immutable captures. Results are never labels."""
import json,sqlite3,threading,time
from capture import now

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
        # Serial worker; a completed rejection is evidence and is not retried forever.
        with self.lock:
            if self.reader is None:return False
            with self.store.connect() as db:
                row=db.execute('SELECT f.sha256 FROM capture_events e JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id WHERE NOT EXISTS (SELECT 1 FROM inference i WHERE i.sha256=f.sha256 AND i.pipeline=?) ORDER BY e.event_id LIMIT 1',(self.reader.pipeline_id,)).fetchone()
            if not row:return False
            digest=row[0];start=time.perf_counter()
            try:
                result=self.reader.read_jpeg(self.store.image(digest))
            except Exception as exc:
                result={'state':'rejected','error':str(exc) if isinstance(exc,ValueError) else type(exc).__name__,
                        'dial_positions':[],'physical_value':None}
            result.update(source_sha256=digest,pipeline_id=self.reader.pipeline_id,training_allowed=False,accuracy_verified=False)
            result['total_processing_seconds']=time.perf_counter()-start
            encoded=json.dumps(result,allow_nan=False)
            with self.store.connect() as db:
                db.execute('INSERT INTO inference VALUES(?,?,?,?)',(digest,self.reader.pipeline_id,now(),encoded))
            return True
    def latest(self):
        # Snapshot the active pipeline while holding the same lock as activation.
        with self.lock:
            if self.reader is None:return {'state':'not_configured'}
            pipeline=self.reader.pipeline_id
        with self.store.connect() as db:
            row=db.execute('SELECT f.sha256 FROM capture_events e JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id ORDER BY e.event_id DESC LIMIT 1').fetchone()
            if not row:return {'state':'waiting_for_image'}
            result=db.execute('SELECT result FROM inference WHERE sha256=? AND pipeline=?',(row[0],pipeline)).fetchone()
        if not result:return {'state':'pending','source_sha256':row[0]}
        try:
            value=json.loads(result[0])
            json.dumps(value,allow_nan=False)
            if not isinstance(value,dict) or value.get('state') not in ('estimated','rejected') or value.get('pipeline_id')!=pipeline or value.get('source_sha256')!=row[0]:
                raise ValueError('invalid_stored_result')
            rows=value.get('dial_positions',[])
            if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):raise ValueError('invalid_dial_results')
            return value
        except (ValueError,TypeError,RecursionError):
            # Preserve the evidence; never substitute a previous image's result.
            return {'state':'unavailable','error':'stored_result_invalid','source_sha256':row[0],
                    'pipeline_id':pipeline,'training_allowed':False,'accuracy_verified':False}
    def run(self):
        while not self.stop.is_set():
            try:
                worked=self.once();self.last_error=None
                if not worked:self.stop.wait(1)
            except (OSError,sqlite3.Error):
                self.last_error='recognition_storage_unavailable';self.stop.wait(5)
