"""Camera Setup display state. Reading a snapshot never touches the camera."""
import hashlib
import json
import re
from datetime import date
from pathlib import Path

from camera_image import capabilities as image_capabilities, validate as validate_image
from camera_lighting import PINS, TYPES, capabilities as lighting_capabilities, integer, unique
from setup_store import Setup


def panel(key, value, backup=False):
    if (not isinstance(value, dict) or not isinstance(value.get('revision'), str)
            or not re.fullmatch('[0-9a-f]{64}', value['revision'])):
        raise ValueError('invalid_control_revision')
    result = {'revision': value['revision']}
    if backup:
        result['backup_date'] = date.fromisoformat(value['backup_date']).isoformat()
    caps = value.get('capabilities')
    if key == 'settings':
        light = value['lighting']
        if (set(light) != {'source', 'pin', 'count', 'type', 'channels', 'intensity'}
                or light['source'] not in ('builtin', 'strip') or light['type'] not in TYPES
                or integer(light['pin'], 0, 39) not in PINS or not isinstance(light['channels'], list)
                or len(light['channels']) != 4 or (light['type'] != 'SK6812_RGBW' and light['channels'][3])):
            raise ValueError('invalid_saved_lighting')
        integer(light['count'], 1, 100000)
        integer(light['intensity'], 0, 100)
        for channel in light['channels']:
            integer(channel, 0, 255)
        result['lighting'] = light
        if not backup:
            result['capabilities'] = lighting_capabilities({**caps, 'version': 1})
    elif key == 'image_settings':
        if not backup:
            result['capabilities'] = image_capabilities({**caps, 'mode': 'remote-camera', 'saved_controls_apply': True})
        # Backups can provide saved values without identifying the sensor.
        # Use the widest supported range solely for a read-only display.
        result['controls'] = validate_image(value['controls'], 'OV5640' if backup else caps['model'])
    else:
        raise ValueError('invalid_panel')
    return result


class CameraControlSnapshot:
    def __init__(self, directory, origin):
        self.source = hashlib.sha256(origin.encode('utf8')).hexdigest()
        self.path = Path(directory) / 'camera-setup-controls.json'
        self.backup = self.read(self.path.with_name('camera-setup-backup.json'), backup=True)
        self.saved = self.read(self.path)
        self.save_failed = False

    def read(self, path, backup=False):
        try:
            with path.open('rb') as stream:
                raw = stream.read(8193)
            if len(raw) > 8192:
                return {}
            document = json.loads(raw, object_pairs_hook=unique)
            if document['source'] != self.source or type(document['version']) is not int or document['version'] != 1:
                return {}
            return {key: panel(key, value, backup) for key, value in document['panels'].items()}
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError):
            return {}

    def display(self):
        return {**self.backup, **self.saved}

    def record(self, result, previous_revision):
        updated = dict(self.saved)
        for key in ('settings', 'image_settings'):
            if key not in result:
                continue
            value = result[key]
            try:
                updated[key] = panel(key, value)
            except (ValueError, KeyError, TypeError, AttributeError):
                self.save_failed = True
                return
            peer = 'image_settings' if key == 'settings' else 'settings'
            if (peer not in result and peer in updated and value.get('active_verified') is True
                    and updated[peer]['revision'] == previous_revision):
                updated[peer] = {**updated[peer], 'revision': updated[key]['revision']}
        if updated == self.saved and not self.save_failed:
            return
        self.saved = updated
        payload = json.dumps(dict(version=1, source=self.source, panels=updated), allow_nan=False).encode('ascii')
        try:
            Setup._atomic(self.path, payload)
            self.save_failed = False
        except OSError:
            # The camera transaction already finished. A cache write failure must
            # never turn it into a failed camera operation or invite a retry.
            self.save_failed = True
