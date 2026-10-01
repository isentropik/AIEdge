"""Explicit setup photos, separate from scheduled captures and reading evidence."""
import threading
import uuid
from capture import validate
from capture_clock import parse as parse_clock


class CameraSetup:
    def __init__(self, camera, setup, interval, capture_enabled):
        self.camera, self.setup = camera, setup
        self.interval, self.capture_enabled = interval, capture_enabled
        self.stop = threading.Event()
        self.condition = threading.Condition()
        self.pending = None
        self.snapshot = {'state': 'idle', 'configured': camera is not None,
                         'camera_url': camera.origin if camera else None,
                         'interval_seconds': interval, 'capture_enabled': capture_enabled,
                         'camera_settings_supported': False}

    def status(self):
        with self.condition:
            return dict(self.snapshot)

    def start(self, action):
        if action not in ('check', 'picture'):
            raise ValueError('invalid_camera_setup_action')
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
            self.pending = (job, action)
            for key in ('error', 'reference_sha256', 'captured_at', 'image_sha256', 'readiness'):
                self.snapshot.pop(key, None)
            self.snapshot.update(state='queued', job=job, action=action)
            self.condition.notify()
            return dict(self.snapshot)

    def once(self):
        with self.condition:
            if self.pending is None or self.stop.is_set():
                return False
            job, action = self.pending
            self.pending = None
            self.snapshot['state'] = 'working'
        try:
            readiness = self.camera.readiness()
            result = {'readiness': readiness}
            if action == 'picture':
                if readiness.get('state') != 'ready':
                    raise ValueError('camera_not_ready')
                blob, headers = self.camera.capture()
                _, captured_at, digest = validate(blob, headers)
                if parse_clock(headers) is None:
                    raise ValueError('incomplete_capture_clock')
                # This is a reference candidate, not a capture event or a label.
                reference = self.setup.add_reference(blob)
                result.update(reference_sha256=reference, captured_at=captured_at,
                              image_sha256=digest)
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
                     'camera_clock_changed'}
            code = str(error) if str(error) in known else 'camera_setup_failed'
            with self.condition:
                self.snapshot.update(state='error', error=code)
        return True

    def run(self):
        while not self.stop.is_set():
            if not self.once():
                self.stop.wait(.1)
