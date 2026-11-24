"""Meter interpretation identities and byte-checked adoption of dev114/115 history."""
import hashlib
import inspect
import json
from pathlib import Path

import capture_recovery
from event_selection import digest

OBSERVATION = (
    'event_recognition.py', 'event_selection.py', 'event_mode.py', 'ha_event_selection.py',
    'event_selection_config.py', 'event_observation_read.py', 'selector_observation.py',
    'wheel_capture_policy.py', 'reader.py', 'recognition.py', 'observation_support.py',
    'consumption.py', 'accounting_native.py', 'capture_clock.py', 'reading_format.py',
)
ACCOUNTING = ('consumption.py', 'accounting_native.py', 'reading_format.py', 'capture_clock.py',
              'recognition.py', 'temporal_reading.py', 'reading_bounds.py', 'observation_support.py')
EVENT_SOURCES = ('event_recognition.py', 'event_selection.py', 'wheel_capture_policy.py')

# Only these two byte-for-byte refactors moved identity calculation out of the
# reader/accountant. An edit to their interpretation logic invalidates adoption.
LEGACY_REFACTORS = {
    'e65116e56f36002a77bb4534b146e0e09141653c10398f8f9e3fb2ddbd8c7146': 'b9bd7216479645dbfcd12290c4aab87fecfaa6fd1d041654e1c7f00234f1cf13',
    '2c6084ad708096ff967f4f0fbd8223a174b9238482664818e3f62042f7c1694c': '1d165ff8f76e0c692da1001ea17fc8ce55f2c754b3799300c1e0ead941d159db',
}
LEGACY_BOUNDARY = '5e838bcab496920356133cfc9f687bf4ede56cd562c658d524ddcd9f4188772b'
LEGACY_RECOVERY = 'a568e60f0cd1604a8a03329df54501dfac153abe6245430d633272da007761b2'
LEGACY_CAPTURE = (
    'bbe7c6bf52c3b26c8135c394947df7c9587c8119c2332e798fa891403eb77ad9',
    '7aa38fca2192bbf2bdb7eadd9f3d5b2add531a9ac5ab4ac0c05efde629698bf2',
)

def source_hashes(names):
    # Exact dev120 extensions introduce an additional, explicitly packet-bound input.
    # The interpretation of existing JPEG observations retains its prior identity.
    extensions = {'9e446c877c2011d8b6007775dcedf54e0a349b9726e893ab1ef9376afea1c3a7': 'e65116e56f36002a77bb4534b146e0e09141653c10398f8f9e3fb2ddbd8c7146', 'a53a1e66cab63ea67ad3a9c7327421419ea76536c05500bb427a1d853ca2bc07': '042c9c890ea7f231e4e9ec0e0da9b6ee737b66784153088cd56683534b630541'}
    hashes={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in names}
    return {name:extensions.get(value,value) for name,value in hashes.items()}

def boundary_hash():
    # Only the persisted failure-boundary query is used to interpret photos.
    return hashlib.sha256(inspect.getsource(capture_recovery.boundary).encode()).hexdigest()

def legacy_sources(sources):
    return {name: LEGACY_REFACTORS.get(value, value) for name, value in sources.items()}

def observation(db, format_id, pipeline, document, configuration, capabilities):
    sources = source_hashes(OBSERVATION)
    boundary = boundary_hash()
    inputs = dict(format_id=format_id, pipeline=pipeline, document=document,
                  configuration=configuration, capabilities=capabilities)
    identity = digest(dict(inputs, version=2, sources=sources, failure_boundary=boundary))
    # Adopt only the last installed context. Reusing an older matching context
    # could process intervening events a second time under a different policy.
    saved = db.execute('SELECT context FROM event_selection_contexts ORDER BY first_event DESC, rowid DESC LIMIT 1').fetchone()
    if saved and saved[0] != identity and boundary == LEGACY_BOUNDARY:
        legacy = legacy_sources(sources)
        legacy['capture_recovery.py'] = LEGACY_RECOVERY
        for capture in LEGACY_CAPTURE:
            legacy['capture.py'] = capture
            if digest(dict(inputs, version=1, sources=legacy)) == saved[0]:
                return saved[0]
    return identity

def accounting(db, native, context):
    sources = source_hashes(ACCOUNTING)
    boundary = boundary_hash()
    key = dict(native=native, sources=sources, schema=3, failure_boundary=boundary)
    if context is not None:
        key.update(observation_context=context, event_sources=source_hashes(EVENT_SOURCES))
    def encoded_key(key):
        return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()
    identity = encoded_key(key)
    saved = db.execute('SELECT s.engine_id FROM consumption_active a JOIN consumption_segments s '
                       'ON s.segment_id=a.segment_id WHERE a.singleton=1').fetchone()
    if saved and saved[0] != identity and boundary == LEGACY_BOUNDARY:
        legacy = dict(key, schema=2, sources=legacy_sources(sources))
        del legacy['failure_boundary']
        legacy['sources']['capture_recovery.py'] = LEGACY_RECOVERY
        if context is not None:
            legacy['event_sources'] = legacy_sources(key['event_sources'])
        if encoded_key(legacy) == saved[0]:
            return saved[0]
    return identity
