"""Local retention preferences; never rewrite Supervisor options or meter records."""
import hashlib
import json
from setup_store import Setup

DEFAULTS = dict(recent_events=500, older_images=250, older_megabytes=64)
LIMITS = dict(recent_events=(1, 2000), older_images=(0, 1000), older_megabytes=(0, 256))


def validate(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError('retention_settings_invalid')
    for name, (low, high) in LIMITS.items():
        if type(value[name]) is not int or not low <= value[name] <= high:
            raise ValueError('retention_settings_invalid')
    return dict(value)


def read(root):
    path = root / 'image-retention.json'
    try:
        with path.open('rb') as stream:
            body = stream.read(4097)
    except FileNotFoundError:
        return dict(config=dict(DEFAULTS), revision='default')
    if len(body) > 4096:
        raise ValueError('retention_settings_invalid')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('retention_settings_invalid')
            result[key] = value
        return result
    config = validate(json.loads(body, object_pairs_hook=unique))
    return dict(config=config, revision=hashlib.sha256(body).hexdigest())


def save(root, value, revision):
    # Caller holds the same archive/store locks as irreversible image deletion.
    value = validate(value)
    if read(root)['revision'] != revision:
        raise ValueError('retention_settings_changed_reload')
    body = (json.dumps(value, sort_keys=True) + '\n').encode()
    Setup._atomic(root / 'image-retention.json', body)
    return read(root)
