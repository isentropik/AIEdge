"""Local setup persistence. Validate a complete candidate before atomic activation."""
import hashlib,json,os,re,threading,uuid
from pathlib import Path
from calibration import validate
from saved_file import SavedFile
from capture import MAX_IMAGE
from calibration_builder import build,image_rgb

class Setup:
    def __init__(self,directory,reader_factory,recognition):
        self.root=Path(directory);self.references=self.root/'references';self.references.mkdir(parents=True,exist_ok=True)
        self.factory=reader_factory;self.recognition=recognition;self.lock=threading.Lock();self.active=None
        self.path=self.root/'calibration.json'
        self.saved=SavedFile(self.path);self.draft=None
        try:
            raw=self.saved.read()
            if raw is None:return
            document,digest=validate(json.loads(raw))
        except (ValueError,KeyError,TypeError,UnicodeError):
            self.saved.failed('saved_calibration_invalid');return
        except OSError:
            self.saved.failed('calibration_file_unavailable');return
        self.draft=document
        try:self.reference(document['reference_sha256'])
        except (ValueError,OSError):
            self.saved.failed('saved_reference_unavailable');return
        try:reader=self.factory(document)
        except (ValueError,OSError,RuntimeError):
            self.saved.failed('recognition_runtime_unavailable');return
        self.recognition.activate(reader,lambda:None)
        self.active=(document,digest)
    def reference(self,digest):
        if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('invalid_reference_id')
        try:
            with (self.references/(digest+'.image')).open('rb') as stream:blob=stream.read(MAX_IMAGE+1)
        except FileNotFoundError:raise ValueError('reference_image_not_found') from None
        if len(blob)>MAX_IMAGE or hashlib.sha256(blob).hexdigest()!=digest:raise ValueError('reference_corrupt')
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
            if self.active is None:return {'revision':self.saved.revision,'calibration':json.loads(json.dumps(self.draft)),**self.saved.recovery()}
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
            current=self.active[1] if self.active else self.saved.revision
            if current!=expected_revision:raise ValueError('setup_changed_reload_before_saving')
            self.recognition.activate(candidate,lambda:self.saved.replace(blob,self._atomic,'setup_changed_reload_before_saving'))
            self.active=(document,revision)
        return self.status()
