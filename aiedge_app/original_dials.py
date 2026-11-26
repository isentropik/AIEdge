"""Numeric evidence from one original JPEG, independent of how long the image is kept."""
from hashlib import sha256
import json

from event_selection import digest as checksum, encoded
from observation_support import observed_rows
from reading_bounds import diagnose_inconsistency, feasible_ranges
from reading_format import finite_number, validate


def measure(recognition, faces, document, source_sha, image):
    pipeline = document['pipeline_id']
    if sha256(image).hexdigest() != source_sha:
        raise ValueError('original_dial_image_mismatch')
    with recognition.lock:
        reader = recognition.reader
        if reader is None or reader.pipeline_id != pipeline:
            raise ValueError('original_dial_pipeline_unavailable')
        try:
            result = reader.read_jpeg(image)
        except RuntimeError as error:
            raise ValueError('original_dial_inference_failed') from error
    if result.get('source_sha256') != source_sha or result.get('pipeline_id') != pipeline:
        raise ValueError('original_dial_source_mismatch')
    dials = document['dials']
    rows = result['dial_positions']
    if len(rows) != len(dials):
        raise ValueError('original_dial_measurement_incomplete')
    positions = [rows[d['index']].get('position') for d in dials]
    finding = dict(version=1, source_sha256=source_sha, pipeline_id=pipeline,
                   calibration=result.get('profile'), positions=positions, bands_ft3=[])
    if result['state'] == 'rejected' and result.get('error') == 'one_or_more_dials_rejected':
        return finding
    if (result['state'] != 'estimated' or observed_rows(result) != [True] * len(dials)
            or not all(finite_number(p) and 0 <= p < 10 for p in positions)):
        raise ValueError('original_dial_measurement_incomplete')
    ranges = feasible_ranges([d['value_per_revolution'] for d in dials], positions,
                             [d['position_error'] for d in dials])
    if ranges['state'] == 'bounded' and not ranges['wraps_register']:
        finding['bands_ft3'] = [[str(lo), str(hi)] for lo, hi in ranges['intervals']]
    elif ranges['state'] == 'inconsistent' and faces:
        indices = diagnose_inconsistency(document, positions).get('dial_indices')
        proof = faces.fit_original(document, result, image, indices)
        if proof:
            finding.update(proof)
    return finding


def saved(db, source_sha, format_id, pipeline):
    row = db.execute('SELECT record, record_sha FROM original_dial_evidence '
                     'WHERE source_sha=? AND format_id=?', (source_sha, format_id)).fetchone()
    if row is None:
        return None
    finding = json.loads(row[0])
    if (checksum(finding) != row[1] or finding['version'] != 1 or finding['format_id'] != format_id
            or finding['source_sha256'] != source_sha or finding['pipeline_id'] != pipeline):
        raise ValueError('original_dial_evidence_mismatch')
    return finding


def preserve(store, recognition, faces, document, source_sha, image):
    """Commit before a retirement becomes visible; repeated attempts must agree."""
    _, fmt = validate(document)
    pipeline = document['pipeline_id']
    with store.connect() as db:
        prior = saved(db, source_sha, fmt, pipeline)
    if prior is not None:
        return bool(prior['bands_ft3'])
    revision = faces.setup.status()['revision']
    finding = measure(recognition, faces, document, source_sha, image)
    if not revision or finding['calibration'] != revision or faces.setup.status()['revision'] != revision:
        raise ValueError('original_dial_calibration_changed')
    finding['format_id'] = fmt
    with store.connect() as db:
        db.execute('INSERT OR IGNORE INTO original_dial_evidence VALUES(?,?,?,?)',
                   (source_sha, fmt, encoded(finding), checksum(finding)))
        if saved(db, source_sha, fmt, pipeline) != finding:
            raise ValueError('original_dial_evidence_conflict')
    return bool(finding['bands_ft3'])
