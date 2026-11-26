"""Apply a single reviewed absolute-register replay before the publisher emits its next state."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from reconcile import EvidenceStore, rebuild

REQUEST_DIGEST = '255052e45604ad51a547e662af18b4510c201e5b57618f18827cb63bdf35f55b'
REQUEST_FILE = Path('/media/aiedge-register-repair/request.json')


def apply_request(register_path, document, request_path=REQUEST_FILE):
    if not request_path.is_file():
        return 'no_request'
    with request_path.open('rb') as stream:
        data = stream.read(16385)
    if hashlib.sha256(data).hexdigest() != REQUEST_DIGEST:
        raise ValueError('unexpected repair request')
    request = json.loads(data)
    identity = request['identity']
    path = Path(register_path)
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=rw', uri=True)) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='meter_repair_receipts'").fetchone():
            if db.execute("SELECT 1 FROM meter_repair_receipts WHERE request_hash=?", (REQUEST_DIGEST,)).fetchone():
                return 'already_applied'
        row = db.execute('SELECT record FROM nominal_register WHERE identity=?', (identity,)).fetchone()
        if not row:
            raise ValueError('checkpoint missing')
        before = json.loads(row[0])
        motion = before['absolute_motion']
        for field, expected in request['expected_old_anchor'].items():
            if motion['display'].get(field) != expected:
                raise ValueError('current anchor differs from the reviewed branch')
        points = []
        corrected = rebuild(EvidenceStore(path.with_name('captures.sqlite3')), document,
                            request['pre_gap'], before, request['anchor'], motion['source'],
                            request['attempt'], on_point=points.append)
        reference = request['reference']
        matches = [point for point in points if point['event_id'] == reference['event_id']]
        if len(matches) != 1 or any(matches[0].get(k) != value for k,value in reference.items()):
            raise ValueError('8:43 replay differs from the reviewed exposure')
        after = json.dumps(dict(before,absolute_motion=corrected), allow_nan=False)
        with db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('UPDATE nominal_register SET record=? WHERE identity=? AND record=?',
                          (after, identity, row[0])).rowcount != 1:
                raise ValueError('publisher checkpoint changed during replay')
            db.execute('CREATE TABLE IF NOT EXISTS meter_repair_receipts '
                       '(request_hash TEXT PRIMARY KEY, identity TEXT NOT NULL, before_record TEXT NOT NULL, '
                       'after_record TEXT NOT NULL, points TEXT NOT NULL)')
            db.execute('INSERT INTO meter_repair_receipts VALUES (?,?,?,?,?)',
                       (REQUEST_DIGEST, identity, row[0], after, json.dumps(points,separators=(',',':'))))
    return 'applied'
