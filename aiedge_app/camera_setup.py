"""Explicit setup photos, separate from scheduled captures and reading evidence."""
import threading
import uuid
from contextlib import nullcontext
from capture import validate
from capture_clock import parse as parse_clock


def image_orientation(headers):
    values = headers.get_all('X-AIEdge-Image-Orientation') if hasattr(headers,'get_all') else (
        [headers['X-AIEdge-Image-Orientation']] if 'X-AIEdge-Image-Orientation' in headers else None)
    if values is None:return None  # Legacy captures cannot prove orientation.
    if len(values)!=1 or values[0] not in ('0','1','2','3'):
        raise ValueError('camera_image_orientation_unverified')
    return int(values[0])


class CameraSetup:
    def __init__(self, camera, setup, interval, capture_enabled, lighting=None, image_controls=None):
        self.camera, self.setup = camera, setup
        self.interval, self.capture_enabled = interval, capture_enabled
        self.lighting = lighting
        self.image_controls = image_controls
        self.stop = threading.Event()
        self.condition = threading.Condition()
        self.pending = None
        self.snapshot = {'state': 'idle', 'configured': camera is not None,
                         'camera_url': camera.origin if camera else None,
                         'interval_seconds': interval, 'capture_enabled': capture_enabled,
                         'camera_settings_supported': False}

    def status(self):
        with self.condition:
            return dict(self.snapshot,lighting_needs_attention=self.lighting.needs_attention() if self.lighting else False,
                        image_needs_attention=self.image_controls.needs_attention() if self.image_controls else False,
                        image_requires_reference=self.image_controls.requires_reference() if self.image_controls else False)

    def start(self, action, revision=None, lighting=None, controls=None):
        if action not in ('check', 'picture', 'lighting-load', 'lighting-apply','image-load','image-apply'):
            raise ValueError('invalid_camera_setup_action')
        if action.startswith('lighting-') and self.lighting is None:
            raise ValueError('camera_lighting_unsupported')
        if action == 'lighting-apply' and (not isinstance(revision,str) or not isinstance(lighting,dict)):
            raise ValueError('camera_lighting_choice_invalid')
        if action.startswith('image-') and self.image_controls is None: raise ValueError('camera_image_unsupported')
        if action == 'image-apply' and (not isinstance(revision,str) or not isinstance(controls,dict)): raise ValueError('camera_image_choice_invalid')
        with self.condition:
            if self.stop.is_set():
                raise ValueError('camera_setup_stopping')
            if self.camera is None:
                raise ValueError('camera_not_configured')
            if action == 'picture' and self.setup is None:
                raise ValueError('setup_runtime_unavailable')
            if self.pending or self.snapshot['state'] in ('queued', 'working'):
                raise ValueError('camera_setup_busy')
            job = uuid.uuid4().hex
            self.pending = (job, action, revision, lighting, controls)
            for key in ('error', 'reference_sha256', 'captured_at', 'image_sha256', 'image_orientation', 'readiness', 'lighting_needs_attention'):
                self.snapshot.pop(key, None)
            self.snapshot.update(state='queued', job=job, action=action)
            self.condition.notify()
            return dict(self.snapshot)

    def once(self):
        with self.condition:
            if self.pending is None or self.stop.is_set():
                return False
            job, action, revision, lighting, controls = self.pending
            self.pending = None
            self.snapshot['state'] = 'working'
        try:
            with self.camera.operation() if hasattr(self.camera,'operation') else nullcontext():
                if action.startswith('lighting-'):
                    settings = self.lighting.load() if action == 'lighting-load' else self.lighting.apply(revision,lighting)
                    result = {'settings': settings, 'camera_settings_supported': True}
                elif action.startswith('image-'):
                    settings = self.image_controls.load() if action == 'image-load' else self.image_controls.apply(revision,controls)
                    result = {'image_settings':settings,'image_settings_supported':True}
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
                     'camera_image_activation_unverified'}
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
