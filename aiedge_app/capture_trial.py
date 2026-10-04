"""Explicit short image trials; never enable recurring capture or invent labels.

One worker per app process. Startup recovery runs only after the HTTP port has
been acquired. Requests are journaled before camera I/O, so a lost reply or app
restart cannot replay a trial ID. An in-flight capture can finish after cancel;
it is preserved and reported. OS DNS/filesystem stalls are not interruptible.
"""
import copy
import json
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime

from capture import CAMERA_FAILURES, now, validate
from capture_clock import parse as parse_clock, interval as clock_interval

ACTIVE = ('queued', 'working', 'cancelling')
TERMINAL = ('completed', 'cancelled', 'expired', 'failed', 'interrupted')
MAX_JOURNAL_BYTES = 16384
ERRORS = set(CAMERA_FAILURES.values()) | {
    'camera_busy', 'camera_timeout', 'camera_authentication_failed',
    'camera_connection_failed', 'camera_name_unresolved', 'camera_certificate_invalid',
    'camera_redirect_rejected', 'camera_status_invalid', 'camera_api_unavailable',
    'capture_deadline_exceeded', 'image_hash_mismatch', 'invalid_capture_time',
    'invalid_frame_id', 'invalid_jpeg_envelope', 'duplicate_camera_header',
    'camera_lighting_unverified', 'camera_image_unverified', 'auto_restore_unverified',
    'camera_image_reference_required', 'storage_low_space', 'storage_unavailable',
    'trial_clock_unverified', 'trial_not_allowed', 'trial_frame_not_fresh',
    'trial_context_changed',
}

def _unique(entries):
    result={}
    for key,value in entries:
        if key in result:raise ValueError('trial_journal_invalid')
        result[key]=value
    return result

def _timestamp(value):
    if not isinstance(value,str) or not 1<=len(value)<=64:return False
    try:
        stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
        return stamp.tzinfo is not None and stamp.year>=2020
    except ValueError:return False

def decode_snapshot(request_id, encoded):
    """Bound, validate and redact persisted state before use or recovery writes."""
    try:
        if not isinstance(encoded,str) or len(encoded.encode('utf-8'))>MAX_JOURNAL_BYTES:raise ValueError()
        value=json.loads(encoded,object_pairs_hook=_unique,
                         parse_constant=lambda ignored:(_ for _ in ()).throw(ValueError()))
        fields={'request_id','max_attempts','duration_seconds','interval_seconds','job','state',
                'started_at','finished_at','attempts','saved_frames','unique_images','duplicate_images',
                'missed_slots','frames','error','in_flight','counts_complete','capture_outcome_uncertain',
                'context','training_allowed','accuracy_verified'}
        if not isinstance(value,dict) or set(value)!=fields:raise ValueError()
        limits(value['request_id'],value['max_attempts'],value['duration_seconds'],value['interval_seconds'])
        if value['request_id']!=request_id or not isinstance(value['job'],str) or not re.fullmatch('[a-f0-9]{32}',value['job']):raise ValueError()
        if type(value['state']) is not str or value['state'] not in ACTIVE+TERMINAL:raise ValueError()
        if not _timestamp(value['started_at']):raise ValueError()
        if value['state'] in TERMINAL:
            if not _timestamp(value['finished_at']):raise ValueError()
        elif value['finished_at'] is not None:raise ValueError()
        for key in ('in_flight','counts_complete','capture_outcome_uncertain','training_allowed','accuracy_verified'):
            if type(value[key]) is not bool:raise ValueError()
        if value['training_allowed'] or value['accuracy_verified']:raise ValueError()
        if value['state'] in TERMINAL and value['in_flight']:raise ValueError()
        if value['state']=='queued' and value['in_flight']:raise ValueError()
        for key in ('attempts','saved_frames','unique_images','duplicate_images','missed_slots'):
            if type(value[key]) is not int or not 0<=value[key]<=9223372036854775807:raise ValueError()
        frames=value['frames']
        if not isinstance(frames,list) or not len(frames)<=value['attempts']<=value['max_attempts']:raise ValueError()
        if value['in_flight'] and value['attempts']<=len(frames):raise ValueError()
        if value['state']=='queued' and (value['attempts'] or frames):raise ValueError()
        for frame in frames:
            if not isinstance(frame,dict) or set(frame) not in ({'frame_id','captured_at','sha256','clock_id','monotonic_us','added'},{'frame_id','captured_at','sha256','clock_id','monotonic_us','added','event_id','camera'}):raise ValueError()
            if 'event_id' in frame and (type(frame['event_id']) is not int or not 1<=frame['event_id']<=9223372036854775807 or not isinstance(frame['camera'],str) or not 1<=len(frame['camera'])<=2048):raise ValueError()
            if not isinstance(frame['frame_id'],str) or not re.fullmatch('[A-Za-z0-9_.-]{1,128}',frame['frame_id']):raise ValueError()
            if not _timestamp(frame['captured_at']) or not isinstance(frame['sha256'],str) or not re.fullmatch('[a-f0-9]{64}',frame['sha256']):raise ValueError()
            if type(frame['added']) is not bool:raise ValueError()
            if (frame['clock_id'] is None)!=(frame['monotonic_us'] is None):raise ValueError()
            if frame['clock_id'] is not None:
                if not isinstance(frame['clock_id'],str) or not re.fullmatch('[A-Za-z0-9_.-]{1,128}',frame['clock_id']):raise ValueError()
                if type(frame['monotonic_us']) is not int or not 0<=frame['monotonic_us']<=9223372036854775807:raise ValueError()
        if value['saved_frames']!=sum(frame['added'] for frame in frames):raise ValueError()
        if value['unique_images']!=len({frame['sha256'] for frame in frames}):raise ValueError()
        if value['duplicate_images']!=len(frames)-value['unique_images']:raise ValueError()
        error=value['error']
        if error is not None and (not isinstance(error,str) or error not in ERRORS|{'trial_capture_failed','trial_interrupted','trial_storage_unavailable'}):raise ValueError()
        if (value['state'] in ('failed','interrupted'))!=(error is not None):raise ValueError()
        if value['state']=='interrupted' and (error!='trial_interrupted' or value['counts_complete']):raise ValueError()
        context=value['context']
        if not isinstance(context,dict) or not set(context)<= {'pipeline_id','format_revision','calibration_revision','observation_context'}:raise ValueError()
        if any(v is not None and (not isinstance(v,str) or not re.fullmatch('[a-f0-9]{64}',v)) for v in context.values()):raise ValueError()
        if context.get('observation_context') is not None and any('event_id' not in frame for frame in frames):raise ValueError()
        return value
    except (ValueError,TypeError,KeyError,OverflowError,UnicodeError,RecursionError):
        raise ValueError('trial_journal_invalid') from None

SELECT_DOCUMENT="CASE WHEN length(CAST(document AS BLOB))<=16384 THEN document ELSE NULL END"

def limits(request_id, max_attempts, duration_seconds, interval_seconds):
    if not isinstance(request_id, str) or not re.fullmatch('[a-f0-9]{32}', request_id):
        raise ValueError('trial_request_id_invalid')
    for value, low, high in ((max_attempts, 1, 3), (duration_seconds, 1, 90), (interval_seconds, 10, 90)):
        if type(value) is not int or not low <= value <= high:
            raise ValueError('trial_limits_invalid')
    return dict(request_id=request_id, max_attempts=max_attempts,
                duration_seconds=duration_seconds, interval_seconds=interval_seconds)

class CaptureTrial:
    def __init__(self, store, camera, allowed, *, context=lambda: {}, clock=time.monotonic, wait=None):
        self.store, self.camera, self.allowed = store, camera, allowed
        self.clock = clock
        self.context = context
        self.stop = threading.Event()
        self.cancelled = threading.Event()
        self.condition = threading.Condition()
        self.wait = wait or self.cancelled.wait
        self.ready = False
        self.error = None
        self.pending = None
        self.active = None
        self.deadline = None
        with store.lock, store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS capture_trials(request_id TEXT PRIMARY KEY, document TEXT NOT NULL)')

    def _write(self, snapshot):
        try:
            encoded=json.dumps(snapshot,allow_nan=False)
            decode_snapshot(snapshot['request_id'],encoded)
            with self.store.lock, self.store.connect() as db:
                updated=db.execute('UPDATE capture_trials SET document=? WHERE request_id=?',
                                   (encoded, snapshot['request_id']))
                if updated.rowcount!=1:raise ValueError('trial_journal_invalid')
        except (OSError, sqlite3.Error, ValueError) as error:
            self.ready = False
            self.error = 'trial_journal_invalid' if isinstance(error,ValueError) else 'trial_storage_unavailable'
            snapshot.update(state='failed', error=self.error, counts_complete=False,
                            capture_outcome_uncertain=snapshot['in_flight'], in_flight=False)
            raise

    def recover(self):
        """No camera calls. Unfinished requests stay consumed after restart."""
        with self.condition:
            if self.ready:return
            if self.error:return
            try:
                with self.store.lock, self.store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    for request_id, encoded in db.execute('SELECT request_id,'+SELECT_DOCUMENT+' FROM capture_trials').fetchall():
                        snapshot = decode_snapshot(request_id,encoded)
                        if snapshot['state'] in ACTIVE:
                            snapshot.update(state='interrupted', counts_complete=False,
                                            capture_outcome_uncertain=snapshot['in_flight'],
                                            in_flight=False, finished_at=now(), error='trial_interrupted')
                            db.execute('UPDATE capture_trials SET document=? WHERE request_id=?',
                                       (json.dumps(snapshot), request_id))
            except ValueError:
                self.error='trial_journal_invalid';return
            except (OSError,sqlite3.Error):
                self.error='trial_storage_unavailable';return
            # Readiness follows the successful transaction commit, never precedes it.
            self.ready = True
            self.condition.notify_all()

    def status(self, request_id=None):
        if request_id is not None:
            limits(request_id, 3, 90, 30)
        with self.condition:
            if self.error:
                return dict(state='unavailable',ready=False,error=self.error,
                            in_flight=bool(self.active and self.active['in_flight']),
                            counts_complete=False,capture_outcome_uncertain=True,
                            training_allowed=False,accuracy_verified=False)
            if self.active is not None and (request_id is None or self.active['request_id']==request_id):
                return copy.deepcopy(self.active)
            try:
                with self.store.lock, self.store.connect() as db:
                    if request_id is None:
                        row = db.execute('SELECT request_id,'+SELECT_DOCUMENT+' FROM capture_trials ORDER BY rowid DESC LIMIT 1').fetchone()
                    else:
                        row = db.execute('SELECT request_id,'+SELECT_DOCUMENT+' FROM capture_trials WHERE request_id=?',(request_id,)).fetchone()
            except (OSError,sqlite3.Error):
                self.ready=False;self.error='trial_storage_unavailable';return self.status()
            if row:
                try:return decode_snapshot(*row)
                except ValueError:
                    self.ready=False;self.error='trial_journal_invalid';return self.status()
            if request_id is not None:
                return dict(state='not_found',request_id=request_id,training_allowed=False,accuracy_verified=False)
            return dict(state='idle', ready=self.ready,training_allowed=False, accuracy_verified=False)

    def availability(self):
        with self.condition:
            if not self.ready or self.stop.is_set() or self.error:
                return dict(can_start=False,block_reason=self.error or 'trial_not_ready')
            if self.active and self.active['state'] in ACTIVE:
                return dict(can_start=False,block_reason='trial_busy')
        permitted=bool(self.camera and self.allowed())
        return dict(can_start=permitted,block_reason=None if permitted else 'trial_not_allowed')

    def start(self, request_id, max_attempts=3, duration_seconds=90, interval_seconds=30):
        requested = limits(request_id, max_attempts, duration_seconds, interval_seconds)
        with self.condition:
            if not self.ready or self.stop.is_set():raise ValueError('trial_not_ready')
            with self.store.lock, self.store.connect() as db:
                row = db.execute('SELECT '+SELECT_DOCUMENT+' FROM capture_trials WHERE request_id=?', (request_id,)).fetchone()
            if row:
                try:prior = decode_snapshot(request_id,row[0])
                except ValueError:
                    self.ready=False;self.error='trial_journal_invalid';raise
                if any(prior[key] != value for key, value in requested.items()):
                    raise ValueError('trial_request_conflict')
                return self.status() if self.active and self.active['request_id'] == request_id else prior
            if self.active and self.active['state'] in ACTIVE:raise ValueError('trial_busy')
            if not self.allowed() or self.camera is None:raise ValueError('trial_not_allowed')
            self.cancelled.clear()
            self.deadline = self.clock() + duration_seconds
            snapshot = dict(requested, job=uuid.uuid4().hex, state='queued', started_at=now(),
                finished_at=None, attempts=0, saved_frames=0, unique_images=0, duplicate_images=0,
                missed_slots=0, frames=[], error=None, in_flight=False, counts_complete=True,
                capture_outcome_uncertain=False, context=copy.deepcopy(self.context()),
                training_allowed=False, accuracy_verified=False)
            encoded=json.dumps(snapshot,allow_nan=False)
            decode_snapshot(request_id,encoded)
            try:
                with self.store.lock, self.store.connect() as db:
                    db.execute('INSERT INTO capture_trials VALUES(?,?)', (request_id, encoded))
            except (OSError,sqlite3.Error):
                self.ready=False;self.error='trial_storage_unavailable';raise
            self.active = snapshot
            self.pending = request_id
            self.condition.notify_all()
            return copy.deepcopy(snapshot)

    def cancel(self, request_id):
        with self.condition:
            if not self.active or self.active['request_id'] != request_id:raise ValueError('trial_not_active')
            if self.active['state'] not in ACTIVE:return copy.deepcopy(self.active)
            self.cancelled.set()
            self.active['state'] = 'cancelling'
            if self.pending:
                self.pending = None
                self._finish('cancelled')
            else:self._write(self.active)
            return copy.deepcopy(self.active)

    def _finish(self, state, error=None):
        with self.condition:
            self.active.update(state=state, error=error, in_flight=False, finished_at=now())
            self._write(self.active)

    def _stopping(self):
        return self.stop.is_set() or self.cancelled.is_set()

    def once(self):
        with self.condition:
            if self.pending is None:return False
            self.pending = None
            self.active['state'] = 'working'
            self._write(self.active)
            deadline = self.deadline
            due = self.clock()
        try:
            while True:
                if self._stopping():self._finish('cancelled');return True
                if self.clock() >= deadline:self._finish('expired');return True
                if self.active['attempts'] >= self.active['max_attempts']:
                    self._finish('completed');return True
                if self.clock() < due:
                    self.wait(min(.25, due-self.clock(), deadline-self.clock()))
                    continue
                if not self.allowed():raise ValueError('trial_not_allowed')
                if self.context() != self.active['context']:raise ValueError('trial_context_changed')
                self.store.require_space()
                with self.camera.operation():
                    self.camera.require_capture()
                    readiness = self.camera.readiness(deadline=deadline)
                    if self._stopping():self._finish('cancelled');return True
                    if self.clock() >= deadline:self._finish('expired');return True
                    if readiness.get('state') != 'ready':raise ValueError('camera_status_invalid')
                    if not self.allowed():raise ValueError('trial_not_allowed')
                    if self.context() != self.active['context']:raise ValueError('trial_context_changed')
                    with self.condition:
                        if self._stopping():self._finish('cancelled');return True
                        self.active['attempts'] += 1
                        self.active['in_flight'] = True
                        self._write(self.active)
                    blob, headers = self.camera.capture(deadline=deadline)
                frame, stamp, digest = validate(blob, headers)
                clock = parse_clock(headers)
                previous = self.active['frames'][-1] if self.active['frames'] else None
                added = self.store.add(self.camera.origin, blob, headers)
                saved_frame=dict(frame_id=frame,captured_at=stamp,sha256=digest,
                    clock_id=clock[0] if clock else None,monotonic_us=clock[1] if clock else None,added=added)
                if self.active['context'].get('observation_context') is not None:
                    with self.store.connect() as db:
                        event=db.execute('SELECT event_id FROM capture_events WHERE camera=? AND frame_id=?',(self.camera.origin,frame)).fetchone()
                    if event is None:raise sqlite3.DatabaseError('trial_capture_event_missing')
                    saved_frame.update(event_id=event[0],camera=self.camera.origin)
                with self.condition:
                    duplicate = any(row['sha256'] == digest for row in self.active['frames'])
                    self.active['frames'].append(saved_frame)
                    self.active['saved_frames'] += int(added)
                    self.active['unique_images'] += int(not duplicate)
                    self.active['duplicate_images'] += int(duplicate)
                    self.active['in_flight'] = False
                    self._write(self.active)
                # Preserve the verified raw image even if temporal/context checks
                # reject it as trial evidence. It remains excluded from training.
                if clock is None:raise ValueError('trial_clock_unverified')
                if previous:
                    before=dict(previous,camera=self.camera.origin)
                    current=dict(self.active['frames'][-1],camera=self.camera.origin)
                    if clock_interval(before,current)['state'] != 'continuous':raise ValueError('trial_frame_not_fresh')
                if self.context() != self.active['context']:raise ValueError('trial_context_changed')
                due += self.active['interval_seconds']
                current = self.clock()
                if current > due:
                    missed = int((current-due)//self.active['interval_seconds'])+1
                    due += missed*self.active['interval_seconds']
                    with self.condition:
                        self.active['missed_slots'] += missed
                        self._write(self.active)
        except Exception as error:
            code = str(error) if isinstance(error, ValueError) and str(error) in ERRORS else 'trial_capture_failed'
            # A capture begun without a verified saved result has uncertain outcome.
            with self.condition:
                self.active['capture_outcome_uncertain'] |= self.active['in_flight']
                if self.error:return True
            self._finish('failed', code)
            return True

    def run(self):
        self.recover()
        while not self.stop.is_set():
            try:worked=self.once()
            except (OSError,sqlite3.Error,ValueError):worked=False
            if not worked:
                with self.condition:self.condition.wait(.25)
