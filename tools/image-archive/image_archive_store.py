"""Immutable receiver-side image storage. No network, device IO, or training imports.

Raw blobs are content addressed. Capture identity includes device, boot and sensor
capture time, so identical images from distinct captures retain distinct records.
An orphan blob after a failed record write is safe; no receipt is returned until
both objects have been read back. Publication uses non-replacing Windows rename
or POSIX hard links within the destination directory.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from datetime import datetime

MAX_IMAGE_BYTES = 2 * 1024 * 1024
FIELDS = {
    'version', 'device_id', 'boot_id', 'capture_us', 'capture_utc',
    'image_sha256', 'image_bytes', 'firmware_sha256', 'model_sha256',
    'calibration_sha256', 'settings_sha256',
}


class ArchiveConflict(ValueError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def validate_metadata(metadata):
    if not isinstance(metadata, dict) or set(metadata) != FIELDS:
        raise ValueError('Unexpected or missing metadata fields')
    if type(metadata['version']) is not int or metadata['version'] != 1:
        raise ValueError('Unsupported archive version')
    for key in ('device_id', 'boot_id'):
        if not isinstance(metadata[key], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', metadata[key]):
            raise ValueError('Invalid capture identity')
    if type(metadata['capture_us']) is not int or not 0 <= metadata['capture_us'] <= 2**63-1:
        raise ValueError('Invalid sensor capture timestamp')
    if type(metadata['image_bytes']) is not int or not 0 < metadata['image_bytes'] <= MAX_IMAGE_BYTES:
        raise ValueError('Invalid image length')
    for key in FIELDS:
        if key.endswith('_sha256') and (not isinstance(metadata[key], str) or not re.fullmatch('[0-9a-f]{64}', metadata[key])):
            raise ValueError('Invalid SHA-256')
    utc = metadata['capture_utc']
    if utc is not None:
        if not isinstance(utc, str) or len(utc) > 40:
            raise ValueError('Invalid wall-clock capture time')
        parsed = datetime.fromisoformat(utc.replace('Z', '+00:00'))
        if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
            raise ValueError('Wall-clock capture time must explicitly be UTC')
    # Round trip prevents caller mutation while persistence is in progress.
    return json.loads(canonical(metadata))


def sync_directory(path):
    """Commit directory entries on POSIX; portable Windows API is unavailable.

    Errors propagate: a published-but-unsynced file must not get a success receipt.
    This is not proof of storage-controller or network-filesystem durability.
    """
    if os.name != 'posix':
        return False
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return True


def ensure_directory(path):
    if path.parent == path:
        if not path.is_dir():
            raise NotADirectoryError(str(path))
        return
    # Also sync existing ancestors: an earlier failed or concurrent creation
    # must not become a successful retry merely because its directory exists.
    ensure_directory(path.parent)
    try:
        path.mkdir()
    except FileExistsError:
        if not path.is_dir():
            raise
    sync_directory(path.parent)
    sync_directory(path)


def matches_existing(path, data):
    """Compare at most expected size plus one byte, including corrupt retries."""
    with path.open('rb') as stream:
        return stream.read(len(data) + 1) == data


def publish_no_replace(source, destination):
    """Publish without replacement; never use POSIX rename (it overwrites).

    Windows rename rejects an existing destination, including on SMB shares.
    Both names are in the same directory. Errors propagate without copy fallback.
    """
    if os.name == 'nt':
        os.rename(source, destination)
    else:
        os.link(source, destination)


def write_immutable(path, data):
    """Publish a fully written object without overwriting an existing object."""
    ensure_directory(path.parent)
    if path.exists():
        if not matches_existing(path, data):
            raise ArchiveConflict('Existing archive object differs')
        sync_directory(path.parent)
        return False
    fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            publish_no_replace(temporary, path)
            created = True
        except FileExistsError:
            created = False
        if not matches_existing(path, data):
            raise ArchiveConflict('Archive readback mismatch')
        sync_directory(path.parent)
        return created
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass  # Successful Windows rename consumed the temporary name.


def store_capture(root, metadata, image):
    metadata = validate_metadata(metadata)
    if not isinstance(image, bytes) or len(image) != metadata['image_bytes'] or digest(image) != metadata['image_sha256']:
        raise ValueError('Image length or hash mismatch')
    identity = {key: metadata[key] for key in ('device_id', 'boot_id', 'capture_us')}
    capture_id = digest(canonical(identity))
    record = {'capture_id': capture_id, 'metadata': metadata,
              'review_status': 'unreviewed', 'training_eligible': False}
    encoded = canonical(record)
    root = Path(root)
    record_path = root/'captures'/f'{capture_id}.json'
    # Reject conflicting capture metadata before creating an unnecessary blob.
    if record_path.exists() and not matches_existing(record_path, encoded):
        raise ArchiveConflict('Capture identity already has different data')
    write_immutable(root/'blobs'/f"{metadata['image_sha256']}.image", image)
    created = write_immutable(record_path, encoded)
    return {'version': 1, 'capture_id': capture_id,
            'image_sha256': metadata['image_sha256'], 'record_sha256': digest(encoded),
            'duplicate': not created, 'verified_readback': True,
            'review_status': 'unreviewed', 'training_eligible': False}


MAX_SETTINGS_BYTES = 8192


def validate_settings(settings_hash, descriptor):
    if not isinstance(settings_hash, str) or not re.fullmatch('[0-9a-f]{64}', settings_hash):
        raise ValueError('Invalid settings hash')
    if not isinstance(descriptor, bytes) or not 0 < len(descriptor) <= MAX_SETTINGS_BYTES:
        raise ValueError('Invalid settings size')
    if not descriptor.startswith(b'capture-settings-v1\n') or not descriptor.endswith(b'\n'):
        raise ValueError('Unsupported settings descriptor')
    if any(c != 10 and not 32 <= c <= 126 for c in descriptor):
        raise ValueError('Invalid settings encoding')
    if digest(descriptor) != settings_hash:
        raise ValueError('Settings hash mismatch')


def store_settings(root, settings_hash, descriptor):
    validate_settings(settings_hash, descriptor)
    created = write_immutable(Path(root)/'settings'/f'{settings_hash}.txt', descriptor)
    return {'version': 1, 'settings_sha256': settings_hash,
            'verified_readback': True, 'duplicate': not created}


def require_settings(root, settings_hash):
    if not isinstance(settings_hash, str) or not re.fullmatch('[0-9a-f]{64}', settings_hash):
        raise ValueError('Invalid settings hash')
    try:
        with (Path(root)/'settings'/f'{settings_hash}.txt').open('rb') as stream:
            descriptor = stream.read(MAX_SETTINGS_BYTES + 1)
    except FileNotFoundError:
        raise ArchiveConflict('Settings record must be uploaded first') from None
    try:
        validate_settings(settings_hash, descriptor)
    except ValueError:
        raise ArchiveConflict('Stored settings record is corrupt') from None
