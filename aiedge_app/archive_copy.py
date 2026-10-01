"""Isolated NAS copy operation. No credentials, predictions or training labels.

Only Linux-mounted SMB/NFS below /media is admitted. All NAS filesystem calls
belong in the child process, never in capture or HTTP threads.
"""
import hashlib
import json
import os
import re
import stat
import sys
import uuid
from datetime import datetime
from pathlib import Path, PurePosixPath

MAX_IMAGE = 4*1024*1024
MAX_METADATA = 16384
ERRORS = {'archive_mount_unavailable', 'archive_unsupported', 'archive_conflict',
          'archive_source_invalid', 'archive_io_failed', 'archive_request_invalid', 'archive_worker_busy'}


class ArchiveError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(body):
    return hashlib.sha256(body).hexdigest()


def directory_parts(value):
    if not isinstance(value, str) or not value.startswith('/media/') or len(value) > 1024:
        raise ArchiveError('archive_request_invalid')
    parts = value.split('/')[1:]
    if any(part in ('', '.', '..') or any(ord(c) < 32 or c == '\\' for c in part) for part in parts):
        raise ArchiveError('archive_request_invalid')
    return parts


def mounted_target(directory, table):
    """Deepest mount wins: a local submount must not masquerade as the NAS."""
    directory_parts(directory)
    matches = []
    for line in table.splitlines():
        fields = line.split()
        try:
            separator = fields.index('-')
            mount = re.sub(r'\\(040|011|012|134)', lambda m: chr(int(m[1], 8)), fields[4])
            major, minor = map(int, fields[2].split(':'))
            filesystem = fields[separator+1]
            if mount == '/' or directory == mount or directory.startswith(mount.rstrip('/')+'/'):
                matches.append((len(mount), mount, (major, minor), filesystem))
        except (ValueError, IndexError):
            continue
    if not matches:
        raise ArchiveError('archive_mount_unavailable')
    _, mount, device, filesystem = max(matches)
    if filesystem not in ('cifs', 'smb3', 'nfs', 'nfs4') or not mount.startswith('/media/'):
        raise ArchiveError('archive_mount_unavailable')
    relative = PurePosixPath(directory).relative_to(mount).parts
    return mount, device, relative


class MountedFilesystem:
    """Pin a checked network mount and traverse only directories without symlinks."""
    def __init__(self, directory):
        if sys.platform != 'linux' or not hasattr(os, 'O_NOFOLLOW'):
            raise ArchiveError('archive_unsupported')
        mount, device, relative = mounted_target(directory, Path('/proc/self/mountinfo').read_text())
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        fd = os.open('/', flags)
        try:
            for component in PurePosixPath(mount).parts[1:]:
                following = os.open(component, flags, dir_fd=fd)
                os.close(fd); fd = following
            actual = os.fstat(fd).st_dev
            if (os.major(actual), os.minor(actual)) != device:
                raise ArchiveError('archive_mount_unavailable')
            self.device = actual
            for component in relative:
                following = self.directory(fd, component)
                os.close(fd); fd = following
            self.root = fd
        except BaseException:
            os.close(fd); raise

    def close(self, fd):
        os.close(fd)

    def directory(self, parent, name, create=True):
        if create:
            try: os.mkdir(name, 0o700, dir_fd=parent)
            except FileExistsError: pass
        fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        if os.fstat(fd).st_dev != self.device:
            os.close(fd); raise ArchiveError('archive_mount_unavailable')
        return fd

    def read(self, parent, name, limit):
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ArchiveError('archive_conflict')
            body = stream.read(limit+1)
        if len(body) > limit: raise ArchiveError('archive_conflict')
        return body

    def write(self, parent, name, body):
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(body); stream.flush(); os.fsync(stream.fileno())

    def names(self, parent):
        return set(os.listdir(parent))

    def sync(self, parent):
        os.fsync(parent)

    def promote(self, parent, temporary, final):
        # Our published directories are nonempty. Rename cannot replace another
        # completed nonempty directory; concurrent identical copies read it back.
        os.rename(temporary, final, src_dir_fd=parent, dst_dir_fd=parent)


def verify_directory(fs, fd, files):
    if fs.names(fd) != set(files): raise ArchiveError('archive_conflict')
    for name, body in files.items():
        if fs.read(fd, name, len(body)) != body: raise ArchiveError('archive_conflict')


def publish(fs, parent, name, files):
    try:
        existing = fs.directory(parent, name, create=False)
    except FileNotFoundError:
        existing = None
    if existing is not None:
        try: verify_directory(fs, existing, files)
        finally: fs.close(existing)
        return
    # Reuse only an exact content-addressed staging directory. Repeated outages
    # cannot create a fresh 4 MiB orphan on every retry. Never replace old bytes.
    temporary = '.pending-' + digest(canonical({key: digest(value) for key, value in files.items()}))
    staging = fs.directory(parent, temporary)
    try:
        present = fs.names(staging)
        if present - set(files): raise ArchiveError('archive_conflict')
        for filename, body in files.items():
            if filename in present:
                if fs.read(staging, filename, len(body)) != body: raise ArchiveError('archive_conflict')
            else: fs.write(staging, filename, body)
        fs.sync(staging); verify_directory(fs, staging, files)
    finally:
        fs.close(staging)
    try:
        fs.promote(parent, temporary, name)
    except OSError:
        # A competing completed publication is accepted only after exact readback.
        try: target = fs.directory(parent, name, create=False)
        except FileNotFoundError: raise
        try: verify_directory(fs, target, files)
        finally: fs.close(target)
    fs.sync(parent)
    target = fs.directory(parent, name, create=False)
    try: verify_directory(fs, target, files)
    finally: fs.close(target)


def validate_request(request):
    if not isinstance(request, dict) or set(request) != {'directory', 'source', 'metadata'}:
        raise ArchiveError('archive_request_invalid')
    directory_parts(request['directory'])
    metadata = request['metadata']
    expected = {'schema_version', 'source_instance', 'event_id', 'camera_key', 'frame_id',
                'captured_at', 'received_at', 'image_sha256', 'image_bytes', 'clock_id',
                'monotonic_us', 'training_allowed', 'split_status', 'accuracy_verified'}
    if not isinstance(metadata, dict) or set(metadata) != expected:
        raise ArchiveError('archive_request_invalid')
    if any(not isinstance(metadata[field],str) for field in ('source_instance','image_sha256','camera_key')):
        raise ArchiveError('archive_request_invalid')
    if (type(metadata['schema_version']) is not int or metadata['schema_version'] != 1 or type(metadata['event_id']) is not int or not 1 <= metadata['event_id'] <= 9223372036854775807
            or not re.fullmatch('[0-9a-f]{32}', str(metadata['source_instance']))
            or not re.fullmatch('[0-9a-f]{64}', str(metadata['image_sha256']))
            or not re.fullmatch('[0-9a-f]{64}', str(metadata['camera_key']))
            or type(metadata['image_bytes']) is not int or not 4 <= metadata['image_bytes'] <= MAX_IMAGE
            or metadata['training_allowed'] is not False or metadata['accuracy_verified'] is not False
            or metadata['split_status'] != 'unchecked' or len(canonical(metadata)) > MAX_METADATA):
        raise ArchiveError('archive_request_invalid')
    if not isinstance(metadata['frame_id'], str) or not re.fullmatch('[A-Za-z0-9_.-]{1,128}', metadata['frame_id']):
        raise ArchiveError('archive_request_invalid')
    for field in ('captured_at', 'received_at'):
        try:
            value = metadata[field]
            if not isinstance(value, str) or len(value) > 64 or datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is None:
                raise ValueError()
        except ValueError:
            raise ArchiveError('archive_request_invalid') from None
    clock, tick = metadata['clock_id'], metadata['monotonic_us']
    if not (clock is None and tick is None):
        if not isinstance(clock, str) or not re.fullmatch('[A-Za-z0-9_.-]{1,128}', clock) or type(tick) is not int or not 0 <= tick <= 9223372036854775807:
            raise ArchiveError('archive_request_invalid')
    if not isinstance(request['source'], str) or not Path(request['source']).is_absolute(): raise ArchiveError('archive_request_invalid')
    return metadata


def copy(request, filesystem=MountedFilesystem):
    metadata = validate_request(request)
    fd = os.open(request['source'], os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode): raise ArchiveError('archive_source_invalid')
        blob = stream.read(MAX_IMAGE+1)
    if (len(blob) != metadata['image_bytes'] or digest(blob) != metadata['image_sha256']
            or not blob.startswith(b'\xff\xd8') or not blob.endswith(b'\xff\xd9')):
        raise ArchiveError('archive_source_invalid')
    fs = filesystem(request['directory']); opened = [fs.root]
    try:
        for component in ('aiedge', metadata['source_instance']):
            opened.append(fs.directory(opened[-1], component))
        objects = fs.directory(opened[-1], 'objects'); opened.append(objects)
        object_metadata = canonical({'schema_version': 1, 'image_sha256': digest(blob), 'image_bytes': len(blob)})
        publish(fs, objects, metadata['image_sha256'], {'image.jpg': blob, 'object.json': object_metadata})
        events = fs.directory(opened[-2], 'events'); opened.append(events)
        manifest = canonical(metadata); manifest_hash = digest(manifest)
        name = f"{metadata['event_id']:020d}-" + manifest_hash
        publish(fs, events, name, {'capture.json': manifest})
        return {'state': 'copied', 'manifest_sha256': manifest_hash}
    finally:
        for fd in reversed(opened): fs.close(fd)


def child_guard(lock_path, parent_pid):
    """One NAS child, including across a parent crash or an unkillable syscall."""
    if sys.platform != 'linux': raise ArchiveError('archive_unsupported')
    import ctypes, fcntl, signal
    if type(parent_pid) is not int or parent_pid < 1: raise ArchiveError('archive_request_invalid')
    if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
        raise ArchiveError('archive_unsupported')
    if os.getppid() != parent_pid: raise ArchiveError('archive_worker_busy')
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode): raise ArchiveError('archive_request_invalid')
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise ArchiveError('archive_worker_busy') from None
    except BaseException:
        os.close(fd); raise
    return fd


def main():
    result = {'state': 'error', 'code': 'archive_request_invalid'}
    guard = None
    try:
        if len(sys.argv) != 5: raise ArchiveError('archive_request_invalid')
        guard = child_guard(sys.argv[3], int(sys.argv[4]))
        with Path(sys.argv[1]).open('rb') as stream: raw = stream.read(MAX_METADATA+4097)
        if len(raw) > MAX_METADATA+4096: raise ArchiveError('archive_request_invalid')
        result = copy(json.loads(raw))
    except ArchiveError as error:
        result = {'state': 'error', 'code': str(error) if str(error) in ERRORS else 'archive_io_failed'}
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        result = {'state': 'error', 'code': 'archive_io_failed'}
    if len(sys.argv) == 5:
        # Result is local app storage, not on the NAS. Never expose exception text.
        Path(sys.argv[2]).write_bytes(canonical(result))
    if guard is not None: os.close(guard)


if __name__ == '__main__': main()
