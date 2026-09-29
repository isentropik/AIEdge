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
                row=db.execute('SELECT f.sha256 FROM frames f WHERE NOT EXISTS (SELECT 1 FROM inference i WHERE i.sha256=f.sha256 AND i.pipeline=?) ORDER BY f.rowid LIMIT 1',(self.reader.pipeline_id,)).fetchone()
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
            row=db.execute('SELECT sha256 FROM frames ORDER BY rowid DESC LIMIT 1').fetchone()
            if not row:return {'state':'waiting_for_image'}
            result=db.execute('SELECT result FROM inference WHERE sha256=? AND pipeline=?',(row[0],pipeline)).fetchone()
        return json.loads(result[0]) if result else {'state':'pending','source_sha256':row[0]}
    def run(self):
        while not self.stop.is_set():
            try:
                worked=self.once();self.last_error=None
                if not worked:self.stop.wait(1)
            except (OSError,sqlite3.Error):
                self.last_error='recognition_storage_unavailable';self.stop.wait(5)
