"""Explicit setup photos, separate from scheduled captures and reading evidence."""
import threading
import time
import uuid
from contextlib import nullcontext
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.request import Request
from capture import validate
from capture_clock import parse as parse_clock
from camera_control_snapshot import CameraControlSnapshot


def check_camera_login(camera):
    endpoint = '/auth/setup'
    expected = b'Website password is already configured.'
    result = dict(endpoint=endpoint, unauthenticated=None, configured_login=None,
                  expected_body_matched=False, verified=False)
    if not camera.basic:
        return dict(result, error='camera_basic_login_missing')
    deadline = time.monotonic() + 10
    for field in ('unauthenticated', 'configured_login'):
        authenticated = field == 'configured_login'
        headers = {'Authorization': 'Basic ' + camera.basic} if authenticated else {}
        request = Request(camera.origin + endpoint, headers=headers, method='GET')
        request.aiedge_deadline = deadline
        try:
            with camera.opener.open(request, timeout=max(.001, deadline - time.monotonic())) as response:
                result[field] = response.status
                if authenticated and response.status == 200:
                    result['expected_body_matched'] = response.read(len(expected) + 1) == expected
        except HTTPError as exc:
            with exc:
                result[field] = exc.code
        except (HTTPException, OSError, ValueError):
            return dict(result, error='camera_login_request_failed')
        if not authenticated and result[field] != 401:
            return dict(result, error='camera_challenge_unverified')
    result['verified'] = result['configured_login'] == 200 and result['expected_body_matched']
    return result


def image_orientation(headers):
    values = headers.get_all('X-AIEdge-Image-Orientation') if hasattr(headers,'get_all') else (
        [headers['X-AIEdge-Image-Orientation']] if 'X-AIEdge-Image-Orientation' in headers else None)
    if values is None:return None  # Legacy captures cannot prove orientation.
    if len(values)!=1 or values[0] not in ('0','1','2','3'):
        raise ValueError('camera_image_orientation_unverified')
    return int(values[0])


class CameraSetup:
    def __init__(self, camera, setup, interval, capture_enabled, lighting=None, image_controls=None, auto_control=None):
        self.camera, self.setup = camera, setup
        self.interval, self.capture_enabled = interval, capture_enabled
        self.lighting = lighting
        self.image_controls = image_controls
        self.auto_control = auto_control
        directory = getattr(setup, "root", None)
        if directory is None and getattr(lighting, "path", None) is not None:
            directory = lighting.path.parent
        self.controls = CameraControlSnapshot(directory, camera.origin) if directory is not None and camera else None
        self.stop = threading.Event()
        self.condition = threading.Condition()
        self.pending = None
        self.snapshot = {'state': 'idle', 'configured': camera is not None,
                         'camera_url': camera.origin if camera else None,
                         'interval_seconds': interval, 'capture_enabled': capture_enabled,
                         'camera_settings_supported': False}

    def status(self):
        with self.condition:
            return dict(self.snapshot, saved_controls=self.controls.display() if self.controls else {},
                        controls_save_failed=bool(self.controls and self.controls.save_failed),
                        lighting_needs_attention=self.lighting.needs_attention() if self.lighting else False,
                        image_needs_attention=self.image_controls.needs_attention() if self.image_controls else False,
                        image_requires_reference=self.image_controls.requires_reference() if self.image_controls else False,
                        auto_settings=self.auto_control.status() if self.auto_control else None)

    def start(self, action, revision=None, lighting=None, controls=None, automatic=None, orientation=None):
        if action not in ('check', 'picture', 'lighting-load', 'lighting-apply','image-load','image-apply',
                          'auto-mode', 'auto-picture', 'auto-recover'):
            raise ValueError('invalid_camera_setup_action')
        if action.startswith('lighting-') and self.lighting is None:
            raise ValueError('camera_lighting_unsupported')
        if action == 'lighting-apply' and (not isinstance(revision,str) or not isinstance(lighting,dict)):
            raise ValueError('camera_lighting_choice_invalid')
        if action.startswith('image-') and self.image_controls is None: raise ValueError('camera_image_unsupported')
        if action == 'image-apply' and (not isinstance(revision,str) or not isinstance(controls,dict)): raise ValueError('camera_image_choice_invalid')
        if action.startswith('auto-') and self.auto_control is None: raise ValueError('auto_contract_unsupported')
        if action == 'auto-mode' and type(automatic) is not bool: raise ValueError('auto_choice_invalid')
        if action in ('auto-picture', 'auto-recover') and not isinstance(revision, str): raise ValueError('auto_choice_invalid')
        if action == 'auto-picture' and (type(orientation) is not int or orientation not in range(4)): raise ValueError('auto_choice_invalid')
        with self.condition:
            if self.stop.is_set():
                raise ValueError('camera_setup_stopping')
            if self.camera is None:
                raise ValueError('camera_not_configured')
            if action in ('picture', 'auto-picture') and self.setup is None:
                raise ValueError('setup_runtime_unavailable')
            if self.pending or self.snapshot['state'] in ('queued', 'working'):
                raise ValueError('camera_setup_busy')
            job = uuid.uuid4().hex
            self.pending = (job, action, revision, lighting, controls, automatic, orientation)
            for key in ('error', 'reference_sha256', 'captured_at', 'image_sha256', 'image_orientation', 'readiness',
                        'lighting_needs_attention', 'image_settings', 'settings', 'auto_result', 'progress'):
                self.snapshot.pop(key, None)
            self.snapshot.update(state='queued', job=job, action=action)
            self.condition.notify()
            return dict(self.snapshot)

    def apply_controls(self, panel, driver, revision, choice):
        saved = self.controls.display().get(panel, {}) if self.controls else {}
        conflict = 'camera_lighting_conflict' if panel == 'settings' else 'camera_image_conflict'
        if not saved.get('backup_date') or saved['revision'] != revision:
            try:
                return driver.apply(revision, choice)
            except ValueError as error:
                if str(error) != conflict or not self.controls or driver.needs_attention():
                    raise
                current = driver.load()
                with self.condition:
                    self.controls.record({panel:current}, None)
                    self.snapshot[panel] = current
                raise

        # The backup describes the editable starting values, not current hardware.
        # Read current capabilities and rebase only the fields explicitly edited.
        current = driver.load()
        lighting = panel == 'settings'
        field = 'lighting' if lighting else 'controls'
        base, live = saved[field], current[field]
        if set(choice) != set(base):
            raise ValueError('camera_lighting_choice_invalid' if lighting else 'camera_image_choice_invalid')
        edits = {k:v for k,v in choice.items() if v != base[k]}
        if lighting and edits.get('source') == 'builtin':
            edits['pin'] = current['capabilities']['builtin_pin']
        related = (('source','pin'), ('type','channels')) if lighting else (
            ('auto_gain','gain','gain_limit'), ('auto_exposure','dsp_exposure','exposure','compensation'))
        watched = set(edits)
        for group in related:
            if watched.intersection(group):
                watched.update(group)
        if any(live[k] != base[k] and live[k] != edits.get(k,base[k]) for k in watched):
            # Expose the freshly read baseline for review, without any camera write.
            with self.condition:
                self.controls.record({panel:current}, None)
                self.snapshot[panel] = current
            raise ValueError(conflict)
        result = driver.apply(current['revision'], {**live, **edits})
        return {**result, 'previous_revision': current['revision']}

    def once(self):
        with self.condition:
            if self.pending is None or self.stop.is_set():
                return False
            job, action, revision, lighting, controls, automatic, orientation = self.pending
            self.pending = None
            self.snapshot['state'] = 'working'
        try:
            with self.camera.operation() if hasattr(self.camera,'operation') else nullcontext():
                if action == 'auto-mode':
                    result = {'auto_settings': self.auto_control.set_mode(automatic)}
                elif action == 'auto-picture':
                    def progress(value):
                        with self.condition:
                            self.snapshot['progress'] = value
                    result = self.auto_control.picture(revision, orientation, self.setup,
                        cancelled=self.stop.is_set, progress=progress)
                elif action == 'auto-recover':
                    result = self.auto_control.recover(revision)
                elif action.startswith('lighting-'):
                    settings = self.lighting.load() if action == 'lighting-load' else self.apply_controls('settings',self.lighting,revision,lighting)
                    result = {'settings': settings, 'camera_settings_supported': True}
                elif action.startswith('image-'):
                    settings = self.image_controls.load() if action == 'image-load' else self.apply_controls('image_settings',self.image_controls,revision,controls)
                    result = {'image_settings':settings,'image_settings_supported':True}
                    if action == 'image-load' and self.auto_control:
                        result['auto_settings'] = self.auto_control.load()
                else:
                    readiness = self.camera.readiness()
                    result = {'readiness': readiness}
                    if action == 'picture':
                        if hasattr(self.camera,'reference_capture'):
                            self.camera.require_capture(reference=True)
                        elif hasattr(self.camera,'require_capture'):self.camera.require_capture()
                        if readiness.get('state') != 'ready':
                            raise ValueError('camera_not_ready')
                        blob, headers = self.camera.reference_capture() if hasattr(self.camera,'reference_capture') else self.camera.capture()
                        _, captured_at, digest = validate(blob, headers)
                        if parse_clock(headers) is None:
                            raise ValueError('incomplete_capture_clock')
                        orientation = image_orientation(headers)
                        # This is a reference candidate, not a capture event or a label.
                        reference = self.setup.add_reference(blob)
                        if self.image_controls:self.image_controls.reference_taken(reference,headers)
                        result.update(reference_sha256=reference, captured_at=captured_at,
                                      image_sha256=digest, image_orientation=orientation)
            with self.condition:
                if self.controls and ('settings' in result or 'image_settings' in result):
                    panel = result.get('settings') or result['image_settings']
                    self.controls.record(result, panel.get('previous_revision',revision))
                self.snapshot.update(state='ready', **result)
        except Exception as error:
            # Expose only bounded, known codes; never remote response bodies.
            known = {'camera_not_ready', 'camera_busy', 'camera_unavailable',
                     'camera_authentication_failed', 'camera_api_unavailable',
                     'camera_protocol_unsupported', 'camera_status_invalid',
                     'camera_connection_failed', 'camera_timeout',
                     'camera_certificate_invalid', 'camera_settings_unavailable',
                     'reference_must_be_640x480', 'reference_image_unreadable',
                     'image_hash_mismatch', 'invalid_capture_time',
                     'camera_clock_changed', 'camera_lighting_unverified',
                     'camera_lighting_response_invalid', 'camera_lighting_unsupported',
                     'camera_lighting_config_unsupported', 'camera_lighting_choice_invalid',
                     'camera_lighting_pin_unavailable', 'camera_lighting_storage_unavailable',
                     'camera_lighting_conflict', 'camera_lighting_rejected',
                     'camera_lighting_connection_failed', 'camera_lighting_save_unverified',
                     'camera_lighting_activation_unverified',
                     'camera_image_unverified','camera_image_orientation_unverified','camera_image_reference_required',
                     'camera_image_response_invalid','camera_image_unsupported','camera_image_config_unsupported',
                     'camera_image_choice_invalid','camera_image_storage_unavailable','camera_image_conflict',
                     'camera_image_rejected','camera_image_connection_failed','camera_image_save_unverified',
                     'camera_image_activation_unverified',
                     'auto_choice_invalid','auto_contract_unsupported','auto_config_conflict','auto_restore_unverified',
                     'auto_receipt_unverified','auto_image_invalid','auto_clock_unverified','auto_orientation_unverified',
                     'auto_frame_not_fresh','auto_deadline','auto_cancelled','auto_no_usable_image','auto_probe_failed',
                     'auto_storage_full','auto_storage_unavailable','auto_connection_failed','auto_response_invalid',
                     'auto_request_rejected','auto_activation_unverified','auto_save_unverified','auto_recovery_unavailable',
                     'auto_reference_unusable'}
            code = str(error) if str(error) in known else 'camera_setup_failed'
            with self.condition:
                self.snapshot.update(state='error', error=code)
                if self.lighting and self.lighting.needs_attention():
                    self.snapshot['lighting_needs_attention'] = True
        return True

    def run(self):
        while not self.stop.is_set():
            if not self.once():
                self.stop.wait(.1)
