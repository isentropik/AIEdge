"""Meter metadata; changing it never relabels the active physical reading."""
import hashlib, json, threading
from pathlib import Path
from saved_file import SavedFile

UNITS = {'gas': ('ft3', 'm3'), 'water': ('ft3', 'm3', 'L', 'gal_us'), 'electric': ('kWh',)}


def validate(value):
    if (not isinstance(value, dict) or set(value) != {'version', 'type', 'unit'}
            or type(value['version']) is not int or value['version'] != 1
            or not isinstance(value['type'], str) or value['type'] not in UNITS
            or not isinstance(value['unit'], str) or value['unit'] not in UNITS[value['type']]):
        raise ValueError('meter_profile_invalid')
    document = dict(value)
    blob = json.dumps(document, sort_keys=True, separators=(',', ':')).encode()
    return document, hashlib.sha256(blob).hexdigest()


class MeterProfile:
    def __init__(self, directory, atomic):
        self.saved = SavedFile(Path(directory) / 'meter-profile.json')
        self.atomic = atomic
        self.lock = threading.RLock()
        self.active = None
        try:
            raw = self.saved.read()
            if raw is not None:
                self.active = validate(json.loads(raw))
        except (ValueError, KeyError, TypeError, UnicodeError, RecursionError):
            self.saved.failed('saved_meter_profile_invalid')
        except OSError:
            self.saved.failed('meter_profile_file_unavailable')

    def status(self):
        with self.lock:
            return {'revision': self.active[1] if self.active else self.saved.revision,
                    'profile': dict(self.active[0]) if self.active else None,
                    **self.saved.recovery()}

    def save(self, value, revision):
        candidate, identity = validate(value)
        with self.lock:
            current = self.active[1] if self.active else self.saved.revision
            if current != revision:
                raise ValueError('meter_profile_changed_reload')
            blob = json.dumps(candidate, sort_keys=True, indent=2).encode()
            # Even no-op requests check the on-disk baseline before succeeding.
            from saved_file import fingerprint
            if fingerprint(self.saved.path) != self.saved.digest:
                raise ValueError('meter_profile_changed_reload')
            if self.active and identity == current:
                return self.status()
            self.saved.replace(blob, self.atomic, 'meter_profile_changed_reload')
            self.active = candidate, identity
            return self.status()

    def require_unit(self, unit):
        """Called under this lock while an explicit number-format save commits."""
        if self.saved.error:
            raise ValueError('meter_profile_unavailable')
        from saved_file import fingerprint
        if fingerprint(self.saved.path) != self.saved.digest:
            raise ValueError('meter_profile_changed_reload')
        if self.active and unit != self.active[0]['unit']:
            raise ValueError('meter_units_changed_review_format')
