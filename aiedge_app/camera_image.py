"""Strict saved exposure/gain/orientation controls; no legacy preview fallback.

Only an advertised activation contract permits edits. Credentials and raw
configuration stay on the server. Uncertain changes block further captures.
Orientation changes require a new reference/calibration before scheduled use.
"""
import hashlib, json, os, re, threading, time, uuid
from pathlib import Path
from camera_lighting import CameraLighting, LIMIT, digest
from durable_file import sync_directory

FIELDS = {
    'auto_exposure': ('CamAec', bool, 0, 1), 'dsp_exposure': ('CamAec2', bool, 0, 1),
    'exposure': ('CamAecValue', int, 0, 1200), 'compensation': ('CamAeLevel', int, -2, 2),
    'auto_gain': ('CamAgc', bool, 0, 1), 'gain': ('CamAgcGain', int, 0, 30),
    'gain_limit': ('CamGainceiling', int, 0, 6),
    'mirror': ('CamHmirror', bool, 0, 1), 'flip': ('CamVflip', bool, 0, 1)}
GAIN_LABELS = ('X2', 'X4', 'X8', 'X16', 'X32', 'X64', 'X128')

def limits(model):
    if model not in ('OV2640', 'OV3660', 'OV5640'):
        raise ValueError('camera_image_unsupported')
    return 2 if model == 'OV2640' else 5

def capabilities(value):
    if not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1:
        raise ValueError('camera_image_unsupported')
    if value.get('mode') != 'remote-camera' or value.get('saved_controls_apply') is not True:
        raise ValueError('camera_image_unsupported')
    model = value.get('model'); bound = limits(model)
    if type(value.get('compensation_limit')) is not int or value['compensation_limit'] != bound:
        raise ValueError('camera_image_response_invalid')
    if value.get('apply_path') != '/apply-image-controls' or value.get('apply_method') != 'POST':
        raise ValueError('camera_image_response_invalid')
    return {'version': 1, 'model': model, 'compensation_limit': bound,
            'apply_path': '/apply-image-controls', 'apply_method': 'POST'}

def validate(value, model):
    if not isinstance(value, dict) or set(value) != set(FIELDS):
        raise ValueError('camera_image_choice_invalid')
    bound = limits(model)
    for name, (_, kind, low, high) in FIELDS.items():
        if name == 'compensation': low, high = -bound, bound
        if type(value[name]) is not kind or not low <= value[name] <= high:
            raise ValueError('camera_image_choice_invalid')
    return dict(value)

class Config:
    def __init__(self, raw, model):
        self.model = model; limits(model)
        if not isinstance(raw, bytes) or not 1 <= len(raw) <= LIMIT or b'\0' in raw:
            raise ValueError('camera_image_config_unsupported')
        try: self.lines = raw.decode('utf-8').splitlines(keepends=True)
        except UnicodeError: raise ValueError('camera_image_config_unsupported') from None
        self.raw, self.fields = raw, {}; section = None; sections = 0
        names = {field[0].upper() for field in FIELDS.values()}
        for index, line in enumerate(self.lines):
            text = line.strip()
            if text.startswith(('[' , ';[')):
                section = text
                if section == '[TakeImage]': sections += 1
                continue
            if section != '[TakeImage]' or text.startswith(('#', ';')): continue
            match = re.fullmatch(r'([ \t]*)([^=\r\n]+?)([ \t]*=[ \t]*)([^\r\n]*)(\r?\n)?', line)
            if not match: continue
            key = match[2].strip().upper()
            if key not in names: continue
            if key in self.fields: raise ValueError('camera_image_config_unsupported')
            value = re.split('[;#]', match[4], maxsplit=1)[0].strip()
            self.fields[key] = (index, match, value)
        if sections != 1 or set(self.fields) != names:
            raise ValueError('camera_image_config_unsupported')

    def controls(self):
        result = {}
        try:
            for name, (key, kind, _, _) in FIELDS.items():
                text = self.fields[key.upper()][2]
                if kind is bool:
                    if text not in ('true', 'false', '0', '1'): raise ValueError()
                    value = text in ('true', '1')
                elif name == 'gain_limit' and text in GAIN_LABELS:
                    value = GAIN_LABELS.index(text)
                else:
                    if not re.fullmatch('-?[0-9]{1,4}', text): raise ValueError()
                    value = int(text)
                result[name] = value
            return validate(result, self.model)
        except ValueError: raise ValueError('camera_image_config_unsupported') from None

    def plan(self, choice):
        choice = validate(choice, self.model); before = self.controls(); lines = self.lines.copy()
        for name, (key, kind, _, _) in FIELDS.items():
            if before[name] == choice[name]: continue
            index, match, _ = self.fields[key.upper()]
            text = ('true' if choice[name] else 'false') if kind is bool else str(choice[name])
            comment = re.search(r'[ \t]*[;#].*', match[4])
            tail = comment[0] if comment else match[4][len(match[4].rstrip()):]
            lines[index] = match[1] + match[2] + match[3] + text + tail + (match[5] or '')
        raw = ''.join(lines).encode('utf-8')
        if len(raw) > LIMIT or Config(raw, self.model).controls() != choice:
            raise ValueError('camera_image_choice_invalid')
        return raw

class CameraImage:
    def __init__(self, camera, directory):
        self.camera, self.lock = camera, threading.RLock()
        self.operation_lock = threading.Lock()
        self.path = Path(directory) / 'camera-image-operation.json'
        self.pending, self.storage_error = None, False
        self.transport = CameraLighting.__new__(CameraLighting); self.transport.camera = camera
        try:
            if self.path.exists():
                with self.path.open('rb') as stream: raw = stream.read(4097)
                data = json.loads(raw)
                if len(raw) > 4096 or set(data) != {'version', 'before', 'after', 'orientation_changed', 'activation_verified', 'orientation', 'reference_sha256'} \
                        or type(data['version']) is not int or data['version'] != 1 \
                        or any(not isinstance(data[k], str) or not re.fullmatch('[0-9a-f]{64}', data[k]) for k in ('before', 'after')) \
                        or any(type(data[k]) is not bool for k in ('orientation_changed', 'activation_verified')):
                    raise ValueError()
                if type(data['orientation']) is not int or not 0 <= data['orientation'] <= 3 or \
                        (data['reference_sha256'] is not None and (not isinstance(data['reference_sha256'], str)
                        or not re.fullmatch('[0-9a-f]{64}', data['reference_sha256']))): raise ValueError()
                self.pending = data
        except (OSError, ValueError, TypeError, UnicodeError): self.storage_error = True

    def needs_attention(self):
        with self.lock: return self.storage_error or bool(self.pending and not self.pending['activation_verified'])

    def requires_reference(self):
        with self.lock: return bool(self.pending and self.pending['orientation_changed'])

    def require_capture(self, reference=False):
        if self.needs_attention(): raise ValueError('camera_image_unverified')
        if self.requires_reference() and not reference: raise ValueError('camera_image_reference_required')

    def persist(self, data):
        with self.lock: self.pending = data
        temp = self.path.with_name(uuid.uuid4().hex + '.tmp')
        try:
            with temp.open('xb') as stream:
                stream.write(json.dumps(data).encode('ascii')); stream.flush(); os.fsync(stream.fileno())
            os.replace(temp, self.path); sync_directory(self.path.parent)
        except OSError:
            self.storage_error = True
            raise ValueError('camera_image_storage_unavailable') from None
        finally:
            if temp.exists(): temp.unlink()

    def clear(self):
        try: self.path.unlink(); sync_directory(self.path.parent)
        except OSError:
            self.storage_error = True
            raise ValueError('camera_image_storage_unavailable') from None
        with self.lock: self.pending = None

    def request(self, *args, **kwargs):
        try: return self.transport._request(*args, **kwargs)
        except ValueError as error:
            raise ValueError(str(error).replace('camera_lighting_', 'camera_image_')) from None

    def load(self):
        deadline = time.monotonic() + 15
        caps = capabilities(self.request('/image-controls-capabilities', deadline))
        raw = self.request('/fileserver/config/config.ini', deadline, json_response=False)
        return {'revision': digest(raw), 'controls': Config(raw, caps['model']).controls(), 'capabilities': caps,
                'needs_activation': self.needs_attention(), 'requires_reference': self.requires_reference(), 'active_verified': False}

    def apply(self, revision, choice):
        if not self.operation_lock.acquire(blocking=False): raise ValueError('camera_busy')
        try:
            if self.storage_error: raise ValueError('camera_image_storage_unavailable')
            if not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{64}', revision): raise ValueError('camera_image_choice_invalid')
            deadline = time.monotonic() + 20
            caps = capabilities(self.request('/image-controls-capabilities', deadline))
            choice = validate(choice, caps['model'])
            before = self.request('/fileserver/config/config.ini', deadline, json_response=False)
            if digest(before) != revision: raise ValueError('camera_image_conflict')
            parsed = Config(before, caps['model']); old = parsed.controls(); after = parsed.plan(choice)
            if after == before and not self.needs_attention():
                return {'revision': revision, 'controls': old, 'capabilities': caps, 'changed': False,
                        'active_verified': False, 'needs_activation': False, 'requires_reference': self.requires_reference()}
            if self.camera.readiness().get('state') != 'ready' and not self.needs_attention(): raise ValueError('camera_not_ready')
            orientation = any(old[k] != choice[k] for k in ('mirror', 'flip')) or self.requires_reference()
            data = {'version': 1, 'before': digest(before), 'after': digest(after),
                    'orientation_changed': orientation, 'activation_verified': False,
                    'orientation': int(choice['mirror']) + 2 * int(choice['flip']), 'reference_sha256': None}
            self.persist(data)
            if before != after:
                payload = json.dumps({'before': before.decode('utf-8'), 'after': after.decode('utf-8')}, ensure_ascii=False).encode('utf-8')
                if len(payload) > 160 * 1024: raise ValueError('camera_image_config_unsupported')
                saved = self.request('/config-save', deadline, payload)
                if not isinstance(saved, dict) or saved.get('saved') is not True: raise ValueError('camera_image_save_unverified')
                if self.request('/fileserver/config/config.ini', deadline, json_response=False) != after: raise ValueError('camera_image_conflict')
            active = self.request('/apply-image-controls', deadline, after, 'text/plain; charset=utf-8')
            if not isinstance(active, dict) or active.get('saved') is not True or active.get('active') is not True \
                    or active.get('restart_required') is not False or active.get('active_revision') != digest(after):
                raise ValueError('camera_image_activation_unverified')
            if self.request('/fileserver/config/config.ini', deadline, json_response=False) != after: raise ValueError('camera_image_conflict')
            data['activation_verified'] = True
            if orientation: self.persist(data)
            else: self.clear()
            return {'revision': digest(after), 'controls': choice, 'capabilities': caps, 'changed': before != after,
                    'active_verified': True, 'needs_activation': False, 'requires_reference': orientation}
        finally:
            self.operation_lock.release()

    def reference_taken(self, reference_sha256, headers):
        with self.lock:
            if not self.pending or not self.pending['orientation_changed']: return
            if not self.pending['activation_verified']: raise ValueError('camera_image_unverified')
            values = headers.get_all('X-AIEdge-Image-Orientation') if hasattr(headers, 'get_all') else [headers.get('X-AIEdge-Image-Orientation')]
            if values != [str(self.pending['orientation'])] or not re.fullmatch('[0-9a-f]{64}', reference_sha256):
                raise ValueError('camera_image_orientation_unverified')
            data = dict(self.pending, reference_sha256=reference_sha256); self.persist(data)

    def calibration_saved(self, reference_sha256):
        with self.lock:
            if not self.pending or not self.pending['orientation_changed']: return
            if self.pending['activation_verified'] and self.pending['reference_sha256'] is not None \
                    and reference_sha256 == self.pending['reference_sha256']:
                self.clear()
