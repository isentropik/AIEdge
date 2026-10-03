"""Explicit Auto setup, with temporary trials isolated from reading evidence.

The camera must advertise restoration before response. A lost or invalid reply
leaves a durable capture guard; a later status check never clears it. Only the
selected light/exposure pair is saved, in one configuration transaction. Image
quality is a heuristic and is not a claim about recognition accuracy or noise.
"""
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
import uuid
from contextlib import nullcontext
from functools import wraps

import auto_capture
import auto_preview
from camera_image import Config as ImageConfig, capabilities as image_capabilities
from camera_lighting import CameraLighting, Config as LightingConfig, capabilities as lighting_capabilities, digest, unique
from capture import MAX_IMAGE, MIN_FREE_BYTES, camera_header
from durable_file import sync_directory

MAX_RUNS = 128
MAX_TRIAL_BYTES = 256 * 1024 * 1024
PROBE_SECONDS = 25  # Firmware's cooperative 20 seconds plus cleanup/transfer.
CONFIG_PATH = '/fileserver/config/config.ini'
HEX64 = re.compile('[0-9a-f]{64}')
HEX32 = re.compile('[0-9a-f]{32}')


def _hex(value, pattern=HEX64):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _json(path):
    with path.open('rb') as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise ValueError('auto_storage_unavailable')
    return json.loads(raw, object_pairs_hook=unique)


def _write(path, value):
    """Durability precedes any setting request. No credential/config bytes here."""
    temp = path.with_name(uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('xb') as stream:
            stream.write(json.dumps(value, sort_keys=True, allow_nan=False).encode('ascii'))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        sync_directory(path.parent)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def _intent_valid(data):
    return isinstance(data, dict) and set(data) == {
        'version', 'camera', 'stage', 'before', 'after', 'run_id',
        'request_id', 'request_sha256', 'orientation_changed', 'orientation'} \
        and type(data['version']) is int and data['version'] == 1 \
        and data['stage'] in ('probe', 'commit') \
        and all(_hex(data[k]) for k in ('camera', 'before', 'after')) \
        and _hex(data['run_id'], HEX32) \
        and type(data['orientation_changed']) is bool \
        and type(data['orientation']) is int and 0 <= data['orientation'] <= 3 \
        and ((data['stage'] == 'probe' and _hex(data['request_id'], HEX32) and _hex(data['request_sha256']))
             or (data['stage'] == 'commit' and data['request_id'] is None and data['request_sha256'] is None))


def camera_operation(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.camera.operation() if hasattr(self.camera, 'operation') else nullcontext():
            return method(self, *args, **kwargs)
    return call


class ProbeFailure(ValueError):
    def __init__(self, code, partial=b''):
        super().__init__(code)
        self.partial = partial


class CameraAuto:
    def __init__(self, camera, directory, lighting, image_controls):
        self.camera, self.lighting, self.image_controls = camera, lighting, image_controls
        self.root = Path(directory)
        self.path = self.root / 'camera-auto-operation.json'
        self.mode_path = self.root / 'camera-auto.json'
        self.trials = self.root / 'auto-trials'
        self.lock = threading.RLock()
        self.operation_lock = threading.Lock()
        self.pending, self.storage_error, self.mode_error = None, False, False
        self.automatic = True
        self.supported = None
        self.transport = CameraLighting.__new__(CameraLighting)
        self.transport.camera = camera
        try:
            if self.path.exists():
                data = _json(self.path)
                if not _intent_valid(data):
                    raise ValueError()
                self.pending = data
        except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
            self.storage_error = True
        try:
            if self.mode_path.exists():
                data = _json(self.mode_path)
                if not isinstance(data, dict) or set(data) != {'version', 'automatic'} \
                        or type(data['version']) is not int or data['version'] != 1 \
                        or type(data['automatic']) is not bool:
                    raise ValueError()
                self.automatic = data['automatic']
        except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
            self.mode_error = True

    def status(self):
        with self.lock:
            return dict(automatic=self.automatic, needs_attention=bool(self.pending or self.storage_error),
                        supported=self.supported,
                        mode_storage_error=self.mode_error,
                        recovery_available=bool(self.pending and not self.storage_error
                            and self.pending['camera'] == digest(self.camera.origin.encode('utf-8'))))

    def set_mode(self, automatic):
        if type(automatic) is not bool:
            raise ValueError('auto_choice_invalid')
        with self.lock:
            try:
                _write(self.mode_path, dict(version=1, automatic=automatic))
            except OSError:
                self.mode_error = True
                raise ValueError('auto_storage_unavailable') from None
            self.automatic, self.mode_error = automatic, False
            return self.status()

    def require_capture(self, reference=False):
        if self.status()['needs_attention']:
            raise ValueError('auto_restore_unverified')

    def load(self):
        try:
            auto_preview.capabilities(self._request('/temporary-capture-capabilities', time.monotonic() + 15))
            self.supported = True
        except ValueError as error:
            if str(error) != 'auto_contract_unsupported':
                raise
            self.supported = False
        return self.status()

    def _persist(self, data):
        assert _intent_valid(data)
        with self.lock:
            self.pending = dict(data)
            try:
                _write(self.path, data)
            except OSError:
                self.storage_error = True
                raise ValueError('auto_storage_unavailable') from None

    def _clear(self):
        with self.lock:
            try:
                self.path.unlink()
                sync_directory(self.root)
            except OSError:
                self.storage_error = True
                raise ValueError('auto_storage_unavailable') from None
            self.pending = None

    def _request(self, *args, **kwargs):
        try:
            return self.transport._request(*args, **kwargs)
        except ValueError as error:
            code = str(error)
            mapped = {'camera_lighting_unsupported': 'auto_contract_unsupported',
                      'camera_lighting_conflict': 'auto_config_conflict',
                      'camera_lighting_connection_failed': 'auto_connection_failed',
                      'camera_lighting_response_invalid': 'auto_response_invalid',
                      'camera_lighting_rejected': 'auto_request_rejected'}
            raise ValueError(mapped.get(code, code)) from None

    def _intent(self, stage, before, after, run_id, orientation, orientation_changed=False, body=None, request_id=None):
        return dict(version=1, camera=digest(self.camera.origin.encode('utf-8')), stage=stage,
                    before=digest(before), after=digest(after), run_id=run_id,
                    request_id=request_id, request_sha256=digest(body) if body is not None else None,
                    orientation_changed=orientation_changed, orientation=orientation)

    def _space(self):
        try:
            self.trials.mkdir(exist_ok=True)
            runs = list(self.trials.iterdir())
            used = sum(p.stat().st_size for p in self.trials.rglob('*') if p.is_file())
            reserve = (auto_capture.MAX_SHOTS + 1) * MAX_IMAGE + 65536
            if len(runs) >= MAX_RUNS or used + reserve > MAX_TRIAL_BYTES \
                    or shutil.disk_usage(self.root).free < MIN_FREE_BYTES + reserve:
                raise ValueError('auto_storage_full')
        except OSError:
            raise ValueError('auto_storage_unavailable') from None

    def _archive(self, folder, number, blob, metadata):
        """An exclusion archive, deliberately outside Store and inference APIs."""
        try:
            if blob:
                sha = digest(blob)
                target = folder / (sha + '.jpg')
                if target.exists():
                    if target.read_bytes() != blob:
                        raise ValueError('auto_storage_unavailable')
                else:
                    with target.open('xb') as stream:
                        stream.write(blob)
                        stream.flush()
                        os.fsync(stream.fileno())
                sync_directory(folder)
                metadata = dict(metadata, raw_sha256=sha, bytes=len(blob))
            _write(folder / (str(number) + '.json'), dict(metadata, training_allowed=False, accuracy_verified=False))
        except OSError:
            raise ValueError('auto_storage_unavailable') from None

    def _post(self, body, deadline):
        headers = {'Content-Type': 'application/json', 'Cache-Control': 'no-cache'}
        if self.camera.token:
            headers['Authorization'] = 'Bearer ' + self.camera.token
        elif self.camera.basic:
            headers['Authorization'] = 'Basic ' + self.camera.basic
        request = urllib.request.Request(self.camera.origin + '/api/v1/capture/temporary',
                                         data=body, headers=headers, method='POST')
        request.aiedge_deadline = deadline
        parts = []
        try:
            if time.monotonic() >= deadline:
                raise TimeoutError()
            with self.camera.opener.open(request, timeout=min(5, deadline - time.monotonic())) as response:
                if response.status != 200 or camera_header(response.headers, 'Content-Type') != 'image/jpeg':
                    raise ValueError('auto_response_invalid')
                length = camera_header(response.headers, 'Content-Length')
                if not re.fullmatch('[1-9][0-9]{0,7}', length) or response.headers.get_all('Transfer-Encoding') \
                        or not 4 <= int(length) <= MAX_IMAGE:
                    raise ValueError('auto_response_invalid')
                remaining = int(length)
                while remaining:
                    if time.monotonic() >= deadline:
                        raise TimeoutError()
                    block = response.read1(min(65536, remaining))
                    if not block or len(block) > remaining:
                        raise ValueError('auto_response_invalid')
                    parts.append(block)
                    remaining -= len(block)
                if time.monotonic() >= deadline:
                    raise TimeoutError()
                return b''.join(parts), response.headers
        except urllib.error.HTTPError as error:
            code = {401: 'camera_authentication_failed', 403: 'camera_authentication_failed',
                    404: 'auto_contract_unsupported', 405: 'auto_contract_unsupported',
                    409: 'auto_config_conflict', 429: 'camera_busy', 503: 'camera_busy'}.get(error.code, 'auto_request_rejected')
            error.close()
        except urllib.error.URLError as error:
            code = 'camera_certificate_invalid' if isinstance(error.reason, ssl.SSLCertVerificationError) \
                else 'camera_timeout' if isinstance(error.reason, (TimeoutError, socket.timeout)) else 'auto_connection_failed'
        except (TimeoutError, socket.timeout):
            code = 'camera_timeout'
        except (OSError, http.client.HTTPException):
            code = 'auto_connection_failed'
        except ValueError:
            code = 'auto_response_invalid'
        raise ProbeFailure(code, b''.join(parts)) from None

    def _activate(self, raw, deadline):
        for path in ('/apply-lighting', '/apply-image-controls'):
            active = self._request(path, deadline, raw, 'text/plain; charset=utf-8')
            if not isinstance(active, dict) or active.get('saved') is not True or active.get('active') is not True \
                    or active.get('restart_required') is not False \
                    or (path == '/apply-image-controls' and active.get('active_revision') != digest(raw)):
                raise ValueError('auto_activation_unverified')
            if self._request(CONFIG_PATH, deadline, json_response=False) != raw:
                raise ValueError('auto_config_conflict')

    def _orientation_guard(self, intent):
        if intent['orientation_changed']:
            self.image_controls.persist(dict(version=1, before=intent['before'], after=intent['after'],
                orientation_changed=True, activation_verified=True, orientation=intent['orientation'], reference_sha256=None))

    def _guard_other_settings(self):
        self.lighting.require_capture()
        self.image_controls.require_capture(reference=True)

    @camera_operation
    def picture(self, revision, orientation, setup, *, cancelled=lambda: False, progress=lambda value: None):
        if not self.operation_lock.acquire(blocking=False):
            raise ValueError('camera_busy')
        folder = None
        try:
            self.require_capture(reference=True)
            self._guard_other_settings()
            if self.mode_error:
                raise ValueError('auto_storage_unavailable')
            if not _hex(revision) or type(orientation) is not int or orientation not in range(4):
                raise ValueError('auto_choice_invalid')
            deadline = time.monotonic() + 15
            auto_preview.capabilities(self._request('/temporary-capture-capabilities', deadline))
            self.supported = True
            caps = image_capabilities(self._request('/image-controls-capabilities', deadline))
            if caps['model'] != 'OV2640':
                raise ValueError('auto_contract_unsupported')
            pins = lighting_capabilities(self._request('/lighting-capabilities', deadline))
            before = self._request(CONFIG_PATH, deadline, json_response=False)
            if digest(before) != revision:
                raise ValueError('auto_config_conflict')
            light = LightingConfig(before).lighting()
            old = ImageConfig(before, caps['model']).controls()
            old_orientation = int(old['mirror']) + 2 * int(old['flip'])
            # Admission validates the actual selected route before allocating a run.
            LightingConfig(before).plan(light, pins)
            if self.camera.readiness().get('state') != 'ready':
                raise ValueError('camera_not_ready')
            if cancelled():
                raise ValueError('auto_cancelled')
            self._space()
            run_id = uuid.uuid4().hex
            folder = self.trials / run_id
            folder.mkdir()
            sync_directory(self.trials)
            _write(folder / 'run.json', dict(version=1, run_id=run_id, state='testing',
                   training_allowed=False, accuracy_verified=False, physical_behavior_verified=False))
            number = 0

            def probe(choice, policy_deadline):
                nonlocal number
                number += 1
                request_id = uuid.uuid4().hex
                body = auto_preview.request(choice, old_orientation, revision, request_id)
                self._persist(self._intent('probe', before, before, run_id, old_orientation,
                                           body=body, request_id=request_id))
                blob = b''
                try:
                    blob, headers = self._post(body, min(policy_deadline, time.monotonic() + PROBE_SECONDS))
                    auto_preview.receipt(headers, body, revision)
                    shot = auto_capture.verified_shot(choice, blob, headers, old_orientation)
                    self._archive(folder, number, blob, dict(shot.report(), request_id=request_id,
                                      request_sha256=digest(body), restoration_verified=True))
                    self._clear()
                    return blob, headers
                except Exception as error:
                    if isinstance(error, ProbeFailure):
                        blob = error.partial
                    # Request and raw-response hashes survive rejected or lost replies.
                    self._archive(folder, str(number) + '-failed', blob, dict(request_id=request_id, request_sha256=digest(body),
                                  restoration_verified=False, state='failed'))
                    raise

            result = auto_capture.tune(probe, orientation=old_orientation, cancelled=cancelled,
                progress=lambda count, quality: progress(dict(stage='testing', shots=count, quality=quality)))
            if cancelled():
                raise ValueError('auto_cancelled')
            controls = result.selected.choice.controls(orientation)
            selected_light = dict(light, intensity=result.selected.choice.intensity)
            after = ImageConfig(LightingConfig(before).plan(selected_light, pins), caps['model']).plan(controls)
            changed_orientation = old_orientation != orientation or self.image_controls.requires_reference()
            intent = self._intent('commit', before, after, run_id, orientation, changed_orientation)
            self._persist(intent)
            progress(dict(stage='saving', shots=len(result.shots)))
            deadline = time.monotonic() + 25
            # One combined save, even when both light and exposure have changed.
            if before != after:
                payload = json.dumps(dict(before=before.decode('utf-8'), after=after.decode('utf-8')), ensure_ascii=False).encode('utf-8')
                saved = self._request('/config-save', deadline, payload)
                if not isinstance(saved, dict) or saved.get('saved') is not True:
                    raise ValueError('auto_save_unverified')
            if self._request(CONFIG_PATH, deadline, json_response=False) != after:
                raise ValueError('auto_config_conflict')
            self._activate(after, deadline)
            self._orientation_guard(intent)
            self._clear()
            if cancelled():
                raise ValueError('auto_cancelled')
            # Probes never become the reference; get a normal capture after activation.
            progress(dict(stage='reference', shots=len(result.shots)))
            blob, headers = self.camera.reference_capture()
            try:
                normal = auto_capture.verified_shot(result.selected.choice, blob, headers, orientation)
            except Exception:
                self._archive(folder, 'reference-failed', blob, dict(state='normal_reference_unverified'))
                raise
            self._archive(folder, 'reference', blob, dict(normal.report(), state='normal_reference_candidate'))
            if not normal.quality.accepted:
                raise ValueError('auto_reference_unusable')
            captured_at, image_sha = normal.captured_at, normal.sha256
            reference = setup.add_reference(blob)
            self.image_controls.reference_taken(reference, headers)
            report = dict(result.report(), state='ready', saved=True, reference_sha256=reference)
            report['reference_quality'] = normal.quality.report()
            _write(folder / 'run.json', report)
            return dict(reference_sha256=reference, captured_at=captured_at, image_sha256=image_sha, image_orientation=orientation,
                auto_settings=self.status(), auto_result=report,
                settings=dict(revision=digest(after), lighting=selected_light, capabilities=pins,
                    saved=True, changed=after != before, active_verified=True, needs_activation=False),
                image_settings=dict(revision=digest(after), controls=controls, capabilities=caps,
                    changed=after != before, active_verified=True, needs_activation=False, requires_reference=changed_orientation))
        except Exception as error:
            if folder is not None:
                # Never publish arbitrary exception text from network or storage libraries.
                try:
                    _write(folder / 'failure.json', dict(state='failed', needs_attention=self.status()['needs_attention'],
                           training_allowed=False, accuracy_verified=False))
                except OSError:
                    pass
            if isinstance(error, OSError):
                raise ValueError('auto_storage_unavailable') from None
            raise
        finally:
            self.operation_lock.release()

    @camera_operation
    def recover(self, revision):
        """Explicitly reactivate a known saved revision; never resubmit a probe."""
        if not self.operation_lock.acquire(blocking=False):
            raise ValueError('camera_busy')
        try:
            with self.lock:
                pending = dict(self.pending) if self.pending else None
            if self.storage_error or pending is None or not _hex(revision) \
                    or pending['camera'] != digest(self.camera.origin.encode('utf-8')):
                raise ValueError('auto_recovery_unavailable')
            self._guard_other_settings()
            deadline = time.monotonic() + 25
            raw = self._request(CONFIG_PATH, deadline, json_response=False)
            if digest(raw) != revision or revision not in (pending['before'], pending['after']):
                raise ValueError('auto_config_conflict')
            caps = image_capabilities(self._request('/image-controls-capabilities', deadline))
            controls = ImageConfig(raw, caps['model']).controls()
            pins = lighting_capabilities(self._request('/lighting-capabilities', deadline))
            light = LightingConfig(raw).lighting()
            LightingConfig(raw).plan(light, pins)
            self._activate(raw, deadline)
            # A failed commit may have saved either the old or the new revision.
            if pending['stage'] == 'commit' and revision == pending['after']:
                self._orientation_guard(pending)
            self._clear()
            return dict(auto_settings=self.status(),
                settings=dict(revision=revision, lighting=light, capabilities=pins, active_verified=True, needs_activation=False),
                image_settings=dict(revision=revision, controls=controls, capabilities=caps, active_verified=True,
                    needs_activation=False, requires_reference=self.image_controls.requires_reference()))
        finally:
            self.operation_lock.release()
