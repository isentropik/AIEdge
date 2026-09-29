"""Remote camera transport and capture provenance. Never infers training labels."""
import base64,hashlib,json,os,re,shutil,sqlite3,threading,time,urllib.request,urllib.parse,urllib.error,uuid,socket,ssl
from datetime import datetime,timezone
from contextlib import contextmanager
from pathlib import Path
MAX_IMAGE=4*1024*1024
MIN_FREE_BYTES=512*1024*1024

def now():return datetime.now(timezone.utc).isoformat()

def verified_image(path,digest):
    with path.open('rb') as stream:blob=stream.read(MAX_IMAGE+1)
    if len(blob)>MAX_IMAGE or hashlib.sha256(blob).hexdigest()!=digest:
        raise ValueError('stored_image_corrupt')
    return blob

def validate(blob,headers):
    if not 4<=len(blob)<=MAX_IMAGE or not blob.startswith(b'\xff\xd8') or not blob.endswith(b'\xff\xd9'):raise ValueError('invalid_jpeg_envelope')
    frame=headers.get('X-AIEdge-Frame-Id','')
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',frame):raise ValueError('invalid_frame_id')
    stamp=datetime.fromisoformat(headers.get('X-AIEdge-Captured-At','').replace('Z','+00:00'))
    if stamp.tzinfo is None or stamp.year<2020 or stamp.timestamp()>time.time()+60:raise ValueError('invalid_capture_time')
    digest=hashlib.sha256(blob).hexdigest()
    if headers.get('X-AIEdge-SHA256')!=digest:raise ValueError('image_hash_mismatch')
    return frame,stamp.astimezone(timezone.utc).isoformat(),digest

class Store:
    def __init__(self,directory):
        self.root=Path(directory);(self.root/'images').mkdir(parents=True,exist_ok=True);self.lock=threading.Lock()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS frames(camera TEXT,frame_id TEXT,captured_at TEXT,received_at TEXT,sha256 TEXT,bytes INTEGER,training_allowed INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(camera,frame_id))')
            db.execute('CREATE TABLE IF NOT EXISTS failures(received_at TEXT,error TEXT)')
            # Check the existing schema before committing any initialization writes.
            db.execute('SELECT camera,frame_id,captured_at,received_at,sha256,bytes,training_allowed FROM frames LIMIT 0')
            db.execute('SELECT received_at,error FROM failures LIMIT 0')
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='inference'").fetchone():
                db.execute('SELECT sha256,pipeline,processed_at,result FROM inference LIMIT 0')
            db.execute('CREATE TABLE IF NOT EXISTS capture_events(event_id INTEGER PRIMARY KEY AUTOINCREMENT,camera TEXT NOT NULL,frame_id TEXT NOT NULL,UNIQUE(camera,frame_id),FOREIGN KEY(camera,frame_id) REFERENCES frames(camera,frame_id))')
            db.execute('CREATE INDEX IF NOT EXISTS frames_sha256 ON frames(sha256)')
            # Add durable IDs without changing any original capture or image bytes.
            # Existing implicit frame rowids are used only for this one-time ordering.
            db.execute('INSERT INTO capture_events(camera,frame_id) SELECT f.camera,f.frame_id FROM frames f WHERE NOT EXISTS (SELECT 1 FROM capture_events e WHERE e.camera=f.camera AND e.frame_id=f.frame_id) ORDER BY f.rowid')
            if db.execute('SELECT 1 FROM capture_events e LEFT JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id WHERE f.camera IS NULL LIMIT 1').fetchone():
                raise sqlite3.DatabaseError('capture_event_without_frame')
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.root/'captures.sqlite3',timeout=10)
        try:
            with db:yield db
        finally:db.close()
    def storage_status(self):
        try:
            free=shutil.disk_usage(self.root).free
            return dict(state='low_space' if free<MIN_FREE_BYTES+MAX_IMAGE else 'ready',
                        free_bytes=free,reserve_bytes=MIN_FREE_BYTES)
        except OSError:
            return dict(state='unavailable',free_bytes=None,reserve_bytes=MIN_FREE_BYTES)
    def require_space(self,incoming=MAX_IMAGE):
        state=self.storage_status()
        if state['state']=='unavailable':raise ValueError('storage_unavailable')
        if state['free_bytes']<MIN_FREE_BYTES+incoming:raise ValueError('storage_low_space')
    def add(self,camera,blob,headers):
        frame,stamp,digest=validate(blob,headers)
        with self.lock,self.connect() as db:
            # Serialize file+ledger admission even if another process opened this store.
            db.execute('BEGIN IMMEDIATE')
            target=self.root/'images'/(digest+'.jpg')
            if target.exists():verified_image(target,digest)
            prior=db.execute('SELECT captured_at,sha256 FROM frames WHERE camera=? AND frame_id=?',(camera,frame)).fetchone()
            if prior:
                if prior!=(stamp,digest):raise ValueError('frame_identity_conflict')
                if not target.exists():raise ValueError('stored_image_missing')
                return False
            self.require_space(0 if target.exists() else len(blob))
            if not target.exists():
                temp=target.with_name(uuid.uuid4().hex+'.tmp')
                try:
                    with temp.open('xb') as f:f.write(blob);f.flush();os.fsync(f.fileno())
                    os.replace(temp,target)
                finally:
                    if temp.exists():temp.unlink()
            db.execute('INSERT INTO frames VALUES(?,?,?,?,?,?,0)',(camera,frame,stamp,now(),digest,len(blob)))
            db.execute('INSERT INTO capture_events(camera,frame_id) VALUES(?,?)',(camera,frame))
        return True
    def fail(self,error):
        with self.lock,self.connect() as db:db.execute('INSERT INTO failures VALUES(?,?)',(now(),error))
    def recent(self):
        with self.lock,self.connect() as db:
            rows=db.execute('SELECT f.captured_at,f.received_at,f.sha256,f.bytes FROM capture_events e JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id ORDER BY e.event_id DESC LIMIT 50').fetchall()
        return [dict(zip(('captured_at','received_at','sha256','bytes'),row)) for row in rows]
    def history(self,before=None,limit=50):
        if type(limit) is not int or not 1<=limit<=100 or (before is not None and (type(before) is not int or not 1<=before<=9223372036854775807)):
            raise ValueError('invalid_history_cursor')
        condition="WHERE e.event_id<?" if before is not None else ""
        parameters=(before,limit+1) if before is not None else (limit+1,)
        with self.lock,self.connect() as db:
            rows=db.execute("""SELECT e.event_id,f.captured_at,f.received_at,f.sha256,f.bytes,f.frame_id,
                EXISTS(SELECT 1 FROM capture_events prior JOIN frames p ON p.camera=prior.camera AND p.frame_id=prior.frame_id
                       WHERE prior.event_id<e.event_id AND p.sha256=f.sha256)
                FROM capture_events e JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id
                """+condition+" ORDER BY e.event_id DESC LIMIT ?",parameters).fetchall()
        more=len(rows)>limit;rows=rows[:limit]
        names=('event_id','captured_at','received_at','sha256','bytes','frame_id','duplicate_image')
        items=[dict(zip(names,row)) for row in rows]
        for item in items:item['duplicate_image']=bool(item['duplicate_image']);item['training_allowed']=False
        return {'items':items,'next_before':rows[-1][0] if more else None}

    def image(self,digest):
        if not re.fullmatch(r'[a-f0-9]{64}',digest):raise ValueError('invalid_image_id')
        with self.lock,self.connect() as db:
            if not db.execute('SELECT 1 FROM frames WHERE sha256=? LIMIT 1',(digest,)).fetchone():raise FileNotFoundError(digest)
        return verified_image(self.root/'images'/(digest+'.jpg'),digest)
    def status(self):
        with self.lock,self.connect() as db:
            total,unique=db.execute('SELECT COUNT(*),COUNT(DISTINCT sha256) FROM frames').fetchone()
            row=db.execute('SELECT f.captured_at,f.received_at,f.sha256 FROM capture_events e JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id ORDER BY e.event_id DESC LIMIT 1').fetchone()
            failure=db.execute('SELECT received_at,error FROM failures ORDER BY rowid DESC LIMIT 1').fetchone()
            failed=db.execute('SELECT COUNT(*) FROM failures').fetchone()[0]
        return dict(captures=total,unique_images=unique,duplicate_images=total-unique,failures=failed,latest=dict(zip(('captured_at','received_at','sha256'),row)) if row else None,last_error=dict(zip(('at','error'),failure)) if failure else None,recognition='not_connected',training_allowed=False,storage=self.storage_status())

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('camera_redirect_rejected')

# Only recognized firmware messages leave this boundary. Never expose response
# bodies, authentication headers, URLs containing secrets, or arbitrary exceptions.
CAMERA_FAILURES={
    'Camera busy; retry shortly':'camera_busy',
    'Camera unavailable; connect it with power off, then restart':'camera_unavailable',
    'Camera clock is not synchronized':'camera_clock_unsynchronized',
    'Frame is stale or clock changed during capture':'camera_clock_changed',
    'Camera settings are not ready':'camera_settings_unavailable',
    'Saved camera settings could not be applied':'camera_settings_unavailable',
    'Illumination failed':'camera_lighting_failed',
    'Light off failed; image rejected':'camera_lighting_failed',
    'Live capture unavailable in demo mode':'camera_demo_mode',
    'Capture worker unavailable':'camera_worker_unavailable',
}

class Camera:
    def __init__(self,url,token='',username='',password=''):
        p=urllib.parse.urlsplit(url)
        if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ('','/') or any(c.isspace() or ord(c)<32 for c in url) or (p.port is not None and not 1<=p.port<=65535):raise ValueError('camera_url_must_be_an_http_origin')
        if any(ord(c)<33 or ord(c)>126 for c in token):raise ValueError('invalid_camera_token')
        if token and (username or password):raise ValueError('choose_one_camera_auth_method')
        if bool(username)!=bool(password) or ':' in username or any(c in username+password for c in ('\r','\n')):raise ValueError('invalid_camera_credentials')
        self.origin=url.rstrip('/');self.token=token
        self.basic=base64.b64encode((username+':'+password).encode('utf-8')).decode('ascii') if username else None
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def capture(self):
        headers={'Content-Type':'application/json'}
        if self.token:headers['Authorization']='Bearer '+self.token
        elif self.basic:headers['Authorization']='Basic '+self.basic
        request=urllib.request.Request(self.origin+'/api/v1/capture',data=b'{}',headers=headers,method='POST');start=time.monotonic()
        try:
            with self.opener.open(request,timeout=5) as r:
                if r.status!=200 or r.headers.get_content_type()!='image/jpeg':raise ValueError('invalid_camera_response')
                length=int(r.headers.get('Content-Length','0'))
                if not 4<=length<=MAX_IMAGE:raise ValueError('invalid_image_length')
                parts=[];remaining=length
                while remaining:
                    if time.monotonic()-start>20:raise ValueError('capture_deadline_exceeded')
                    block=r.read1(min(65536,remaining))
                    if not block:raise ValueError('truncated_image')
                    parts.append(block);remaining-=len(block)
                return b''.join(parts),r.headers
        except urllib.error.HTTPError as exc:
            try:
                try:body=exc.read(257).decode('utf-8',errors='replace').strip()
                except OSError:body=''
                code={401:'camera_authentication_failed',403:'camera_authentication_failed',
                      404:'camera_api_unavailable',405:'camera_api_unavailable',
                      409:'camera_busy',429:'camera_busy',503:'camera_unavailable'}.get(exc.code,'camera_http_error')
                if exc.code==503 and len(body)<=256:code=CAMERA_FAILURES.get(body,code)
            finally:exc.close()
            raise ValueError(code) from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason,ssl.SSLCertVerificationError):code='camera_certificate_invalid'
            elif isinstance(exc.reason,(TimeoutError,socket.timeout)):code='camera_timeout'
            elif isinstance(exc.reason,socket.gaierror):code='camera_name_unresolved'
            else:code='camera_connection_failed'
            raise ValueError(code) from None
        except (TimeoutError,socket.timeout):
            raise ValueError('camera_timeout') from None

class Collector:
    def __init__(self,store,camera,interval):
        self.store,self.camera,self.interval=store,camera,interval;self.stop=threading.Event();self.missed_slots=0;self.last_error=None
    def once(self):
        try:
            self.store.require_space()
            blob,headers=self.camera.capture();self.store.add(self.camera.origin,blob,headers)
            self.last_error=None
        except Exception as e:
            self.last_error={'at':now(),'error':str(e) if isinstance(e,ValueError) else type(e).__name__}
            # A full or unavailable filesystem must not kill the capture worker.
            try:self.store.fail(self.last_error['error'])
            except (OSError,sqlite3.Error):pass
    def run(self):
        due=time.monotonic()
        while not self.stop.is_set():
            self.once();due+=self.interval;current=time.monotonic()
            if current>due:
                missed=int((current-due)//self.interval)+1;self.missed_slots+=missed;due+=missed*self.interval
            self.stop.wait(max(0,due-time.monotonic()))
