"""Human-entered positions on immutable images. Review never admits training data."""
import hashlib,json,math,re,threading
from copy import deepcopy
from capture import now

MAX_REVIEW_BYTES=262144
HASH=re.compile(r"[a-f0-9]{64}")

class ReviewConflict(ValueError):pass

def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value):return hashlib.sha256(encoded(value).encode()).hexdigest()
def positions(values,count):
    if not isinstance(values,list) or len(values)!=count:raise ValueError('Enter one position or unknown for each dial.')
    if any(value is not None and (type(value) not in (int,float) or not 0<=value<10 or not math.isfinite(value)) for value in values):
        raise ValueError('Dial positions must be from 0 up to 10, excluding 10. Leave unreadable dials blank.')
    return values

def event(db,event_id):
    if type(event_id) is not int or not 1<=event_id<=9223372036854775807:raise ValueError('Invalid capture ID.')
    row=db.execute('SELECT e.event_id,f.captured_at,f.received_at,f.sha256,f.frame_id FROM capture_events e JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id WHERE e.event_id=?',(event_id,)).fetchone()
    if row is None:raise FileNotFoundError('Capture not found.')
    result=dict(zip(('event_id','captured_at','received_at','sha256','frame_id'),row))
    result['matching_captures']=db.execute('SELECT COUNT(*) FROM frames WHERE sha256=?',(result['sha256'],)).fetchone()[0]
    return result

class Reviews:
    def __init__(self,store,recognition):
        self.store,self.recognition=store,recognition
        with store.lock,store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS human_reviews(id INTEGER PRIMARY KEY AUTOINCREMENT,sha256 TEXT NOT NULL,context_id TEXT NOT NULL,revision TEXT NOT NULL UNIQUE,document TEXT NOT NULL)')
            db.execute('SELECT id,sha256,context_id,revision,document FROM human_reviews LIMIT 0')
            db.execute('CREATE INDEX IF NOT EXISTS human_reviews_image ON human_reviews(sha256,context_id,id)')
            db.execute("CREATE TRIGGER IF NOT EXISTS human_reviews_no_update BEFORE UPDATE ON human_reviews BEGIN SELECT RAISE(ABORT,'review_history_is_append_only'); END")
            db.execute("CREATE TRIGGER IF NOT EXISTS human_reviews_no_delete BEFORE DELETE ON human_reviews BEGIN SELECT RAISE(ABORT,'review_history_is_append_only'); END")
    def context(self):
        # Called under recognition.lock, the same boundary as calibration activation.
        reader=self.recognition.reader if self.recognition else None
        if reader is None:return None
        calibration=deepcopy(reader.runtime.document) if getattr(reader,'runtime',None) else None
        value={'pipeline_id':reader.pipeline_id,'profile':reader.profile,'model_hashes':deepcopy(getattr(reader,'hashes',{})),'calibration':calibration,
               'dials':[{'index':i,'name':d['name'],'direction':d['direction'],'model':d['model']} for i,d in enumerate(reader.dials)]}
        return {**value,'id':digest(value)}
    @staticmethod
    def latest(db,sha,context_id):
        row=db.execute('SELECT revision,CASE WHEN length(CAST(document AS BLOB))<=? THEN document ELSE NULL END FROM human_reviews WHERE sha256=? AND context_id=? ORDER BY id DESC LIMIT 1',(MAX_REVIEW_BYTES,sha,context_id)).fetchone()
        if row is None:return None
        revision,raw=row
        try:
            document=json.loads(raw)
            if digest(document)!=revision or document['sha256']!=sha or document['context']['id']!=context_id:raise ValueError()
            context=document['context'];identity={k:v for k,v in context.items() if k!='id'}
            if digest(identity)!=context_id:raise ValueError()
            if document['provenance']!='human_entered' or document['training_allowed'] is not False or document['accuracy_verified'] is not False or document['schema']!=1:raise ValueError()
            positions(document['positions'],len(context['dials']))
        except (ValueError,TypeError,KeyError,RecursionError):raise ValueError('Saved review failed its integrity check. Its record has been kept.') from None
        return {**document,'revision':revision}
    def get(self,event_id):
        lock=self.recognition.lock if self.recognition else threading.Lock()
        with lock:
            context=self.context()
            with self.store.lock,self.store.connect() as db:
                capture=event(db,event_id)
                review=self.latest(db,capture['sha256'],context['id']) if context else None
                older=db.execute('SELECT COUNT(*) FROM human_reviews WHERE sha256=? AND context_id!=?',(capture['sha256'],context['id'] if context else '')).fetchone()[0]
            self.store.image(capture['sha256'])
            return {'capture':capture,'context':context,'review':review,'other_context_reviews':older,
                    'training_allowed':False,'accuracy_verified':False}
    def save(self,payload):
        if not isinstance(payload,dict) or set(payload)!={'event_id','context_id','revision','positions'}:raise ValueError('Invalid review document.')
        expected=payload['revision']
        if expected is not None and (not isinstance(expected,str) or not HASH.fullmatch(expected)):raise ValueError('Invalid review revision.')
        lock=self.recognition.lock if self.recognition else threading.Lock()
        with lock:
            context=self.context()
            if context is None:raise ReviewConflict('Save a calibration before reviewing dial positions.')
            if payload['context_id']!=context['id']:raise ReviewConflict('Calibration or model changed. Reload this review before saving.')
            values=positions(payload['positions'],len(context['dials']))
            with self.store.lock,self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                capture=event(db,payload['event_id'])
                # Verify inside the admission transaction without reacquiring Store.lock.
                from capture import verified_image
                verified_image(self.store.root/'images'/(capture['sha256']+'.jpg'),capture['sha256'])
                previous=self.latest(db,capture['sha256'],context['id'])
                if (previous['revision'] if previous else None)!=expected:raise ReviewConflict('This image was reviewed in another tab. Reload before saving.')
                if previous and previous['positions']==values:return previous
                document={'schema':1,'sha256':capture['sha256'],'context':context,'positions':values,
                          'submitted_at':now(),'source_event_id':capture['event_id'],'previous_revision':expected,
                          'provenance':'human_entered','training_allowed':False,'accuracy_verified':False}
                raw=encoded(document)
                if len(raw.encode())>MAX_REVIEW_BYTES:raise ValueError('Review is too large.')
                revision=hashlib.sha256(raw.encode()).hexdigest()
                db.execute('INSERT INTO human_reviews(sha256,context_id,revision,document) VALUES(?,?,?,?)',(capture['sha256'],context['id'],revision,raw))
            return {**document,'revision':revision}
    def summaries(self,rows):
        lock=self.recognition.lock if self.recognition else threading.Lock()
        with lock:
            context=self.context()
            if not context:return
            with self.store.lock,self.store.connect() as db:
                for row in rows:
                    try:review=self.latest(db,row['sha256'],context['id'])
                    except ValueError:
                        row['review_error']=True;review=None
                    row['reviewed_dials']=sum(v is not None for v in review['positions']) if review else None
                    row['review_dials']=len(context['dials'])
