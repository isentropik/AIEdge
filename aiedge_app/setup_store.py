"""Local setup persistence. Validate a complete candidate before atomic activation."""
import hashlib,json,os,re,threading,uuid
from pathlib import Path
from calibration import load
from calibration_builder import build,image_rgb

class Setup:
    def __init__(self,directory,reader_factory,recognition):
        self.root=Path(directory);self.references=self.root/'references';self.references.mkdir(parents=True,exist_ok=True)
        self.factory=reader_factory;self.recognition=recognition;self.lock=threading.Lock();self.active=None
        self.path=self.root/'calibration.json'
        if self.path.exists():
            document,digest=load(self.path);self.reference(document['reference_sha256'])
            reader=self.factory(document)
            self.recognition.activate(reader,lambda:None)
            self.active=(document,digest)
    def reference(self,digest):
        if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('invalid_reference_id')
        blob=(self.references/(digest+'.image')).read_bytes()
        if hashlib.sha256(blob).hexdigest()!=digest:raise ValueError('reference_corrupt')
        return blob
    def add_reference(self,blob):
        image_rgb(blob);digest=hashlib.sha256(blob).hexdigest();path=self.references/(digest+'.image')
        with self.lock:
            if path.exists():self.reference(digest)
            else:self._atomic(path,blob)
        return digest
    @staticmethod
    def _atomic(path,blob):
        temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            with temp.open('xb') as f:f.write(blob);f.flush();os.fsync(f.fileno())
            if temp.read_bytes()!=blob:raise OSError('setup_write_verification_failed')
            os.replace(temp,path)
        finally:
            if temp.exists():temp.unlink()
    def status(self):
        with self.lock:
            if self.active is None:return {'revision':None,'calibration':None}
            document,revision=self.active
            # Return a copy: callers cannot modify the active profile in place.
            return {'revision':revision,'calibration':json.loads(json.dumps(document))}
    def save(self,reference_id,design,expected_revision):
        reference=self.reference(reference_id)
        document,revision=build(reference,design)
        # Reader constructor performs native geometry and model validation.
        candidate=self.factory(document)
        preview=candidate.read_rgb(image_rgb(reference).tobytes())
        if preview.get('state')!='estimated':raise ValueError('reference_recognition_rejected:'+preview.get('error','unknown'))
        blob=json.dumps(document,sort_keys=True,indent=2,allow_nan=False).encode('utf-8')
        with self.lock:
            current=self.active[1] if self.active else None
            if current!=expected_revision:raise ValueError('setup_changed_reload_before_saving')
            self.recognition.activate(candidate,lambda:self._atomic(self.path,blob))
            self.active=(document,revision)
        return self.status()
