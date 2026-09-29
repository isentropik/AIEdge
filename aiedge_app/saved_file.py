"""Bounded configuration reads and recoverable, conflict-checked replacement.

Callers serialize access with their configuration lock. Recovery never silently
resets a file: its bytes are retained until a validated replacement is saved.
"""
import hashlib, os, shutil, uuid
from pathlib import Path
from durable_file import sync_directory

LIMIT = 262144


def fingerprint(path):
    try:
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    except FileNotFoundError:
        return None


class SavedFile:
    def __init__(self, path):
        self.path = Path(path)
        self.digest = None
        self.error = None
        self.unreadable = False

    def read(self):
        try:
            with self.path.open('rb') as stream:
                raw = stream.read(LIMIT + 1)
            self.digest = fingerprint(self.path)
            if len(raw) > LIMIT:
                raise ValueError('configuration_too_large')
            if hashlib.sha256(raw).hexdigest() != self.digest:
                raise ValueError('configuration_changed_during_read')
            return raw
        except FileNotFoundError:
            return None
        except OSError:
            self.unreadable = True
            raise

    def failed(self, code):
        self.error = code

    @property
    def revision(self):
        return 'recovery:' + self.digest if self.digest else None

    def recovery(self):
        if not self.error:
            return {}
        return {'recovery': {'code': self.error, 'file': self.path.name,
                             'original_preserved': self.digest is not None,
                             'replacement_allowed': not self.unreadable and self.digest is not None}}

    def replace(self, blob, atomic, conflict):
        if self.unreadable:
            raise OSError('configuration_unreadable_restart_required')
        if fingerprint(self.path) != self.digest:
            raise ValueError(conflict)
        if self.error and self.digest:
            recovery = self.path.parent / 'recovery'
            recovery.mkdir(exist_ok=True)
            sync_directory(recovery.parent)
            backup = recovery / (self.path.stem + '-' + self.digest + self.path.suffix)
            if not backup.exists():
                temp = recovery / (uuid.uuid4().hex + '.tmp')
                try:
                    with self.path.open('rb') as source, temp.open('xb') as target:
                        shutil.copyfileobj(source, target, 65536)
                        target.flush()
                        os.fsync(target.fileno())
                    if fingerprint(temp) != self.digest:
                        raise OSError('recovery_copy_verification_failed')
                    os.replace(temp, backup)
                finally:
                    if temp.exists():
                        temp.unlink()
            sync_directory(recovery)
            if fingerprint(backup) != self.digest:
                raise OSError('recovery_copy_verification_failed')
            if fingerprint(self.path) != self.digest:
                raise ValueError(conflict)
        atomic(self.path, blob)
        self.digest = hashlib.sha256(blob).hexdigest()
        self.error = None
