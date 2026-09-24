"""Read-only integrity inventory. Never labels, trains, repairs or deletes images."""
import argparse
from collections import Counter
import json
from pathlib import Path
from image_archive_store import canonical, digest, validate_metadata, validate_settings, MAX_IMAGE_BYTES, MAX_SETTINGS_BYTES


def read_bounded(path, maximum):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Missing, non-file or symlink object')
    with path.open('rb') as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError('Object exceeds size limit')
    return data


def unique_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON key')
        value[key] = item
    return value


def audit(root):
    root = Path(root)
    if not root.is_dir():
        raise ValueError('Archive folder does not exist')
    for name in ('captures', 'blobs', 'settings'):
        if (root/name).is_symlink():
            raise ValueError('Archive subfolder must not be a symlink: ' + name)
    issues = []
    groups = Counter()
    hashes = Counter()
    valid = 0
    unknown_utc = 0
    records = sorted((root/'captures').glob('*.json'))
    for path in records:
        try:
            raw = read_bounded(path, 16384)
            record = json.loads(raw, object_pairs_hook=unique_keys)
            if not isinstance(record, dict) or set(record) != {'capture_id','metadata','review_status','training_eligible'}:
                raise ValueError('Unexpected capture record fields')
            metadata = validate_metadata(record['metadata'])
            identity = {key: metadata[key] for key in ('device_id','boot_id','capture_us')}
            expected_id = digest(canonical(identity))
            if record['capture_id'] != expected_id or path.name != expected_id + '.json':
                raise ValueError('Capture identity or filename mismatch')
            if record['review_status'] != 'unreviewed' or record['training_eligible'] is not False:
                raise ValueError('Immutable archive review/training flags changed')
            if raw != canonical(record):
                raise ValueError('Record is not the receiver canonical representation')
            image = read_bounded(root/'blobs'/(metadata['image_sha256']+'.image'), MAX_IMAGE_BYTES)
            if len(image) != metadata['image_bytes'] or digest(image) != metadata['image_sha256']:
                raise ValueError('Image size or SHA-256 mismatch')
            settings = read_bounded(root/'settings'/(metadata['settings_sha256']+'.txt'), MAX_SETTINGS_BYTES)
            validate_settings(metadata['settings_sha256'], settings)
            hashes[metadata['image_sha256']] += 1
            groups[tuple(metadata[k] for k in ('device_id','firmware_sha256','model_sha256','calibration_sha256','settings_sha256'))] += 1
            valid += 1
            unknown_utc += metadata['capture_utc'] is None
        except (ValueError, OSError, TypeError, KeyError) as exc:
            issues.append({'record': path.name, 'error': str(exc)})
    keys = ('device_id','firmware_sha256','model_sha256','calibration_sha256','settings_sha256')
    return {'version': 1, 'records_checked': len(records), 'valid_records': valid,
            'invalid_records': len(issues), 'unique_image_hashes': len(hashes),
            'repeated_image_records': sum(n-1 for n in hashes.values()),
            'valid_records_without_utc': unknown_utc,
            'capture_groups': [dict(zip(keys, key), records=count) for key,count in sorted(groups.items())],
            'issues': issues, 'training_eligible': False,
            'limits': ['Read-only point-in-time check; concurrent writes can require a later retry.',
                       'No image decoding, needle labels, near-duplicate or held-out split assignment.',
                       'Model and calibration hashes are recorded identities, not verification of external artifacts.',
                       'Only capture records and their referenced objects are checked; no orphan cleanup.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    try:
        result = audit(args.folder)
    except (OSError, ValueError) as exc:
        parser.exit(2, str(exc)+'\n')
    print(json.dumps(result, indent=2))
    return 1 if result['invalid_records'] else 0

if __name__ == '__main__':
    raise SystemExit(main())
