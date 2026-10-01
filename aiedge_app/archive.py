"""Durable, optional archive cursor. NAS I/O runs only in a disposable child.

The capture ledger is the queue: no image copies or unbounded in-memory backlog.
Acknowledgements live separately and never modify readings or training status.
"""
import hashlib, json, os, sqlite3, subprocess, sys, threading, time, uuid
from contextlib import contextmanager
from pathlib import Path
from capture import now
from archive_copy import canonical, directory_parts, validate_request, ERRORS
from durable_file import sync_directory

COPY_DEADLINE = 15
PERMANENT_ERRORS = {'archive_conflict', 'archive_source_invalid', 'archive_request_invalid', 'archive_unsupported'}


class ArchiveConflict(ValueError):
    pass


def choices(value):
    if not isinstance(value, dict) or set(value) != {'enabled', 'directory'} or type(value['enabled']) is not bool:
        raise ValueError('archive_choices_invalid')
    directory = value['directory']
    if not isinstance(directory, str) or (value['enabled'] and not directory):
        raise ValueError('archive_choices_invalid')
    if directory:
        directory_parts(directory)
    return {'enabled': value['enabled'], 'directory': directory}


def revision(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class Archive:
    def __init__(self, store, deadline=COPY_DEADLINE, launcher=None):
        self.store = store
        self.root = store.root / 'archive'
        self.root.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.deadline = deadline
        self.launcher = launcher or self.launch
        self.active = None
        self.last_error = None
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),instance TEXT NOT NULL,enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),directory TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS targets(directory TEXT PRIMARY KEY,cursor INTEGER NOT NULL DEFAULT 0,manifest TEXT,copied_at TEXT,error TEXT,attempts INTEGER NOT NULL DEFAULT 0,retry_at REAL NOT NULL DEFAULT 0,inflight INTEGER)')
            db.execute('INSERT OR IGNORE INTO settings VALUES(1,?,0,?)', (uuid.uuid4().hex, ''))
            instance, enabled, directory = db.execute('SELECT instance,enabled,directory FROM settings WHERE id=1').fetchone()
            if len(instance) != 32 or any(c not in '0123456789abcdef' for c in instance):
                raise ValueError('archive_identity_invalid')
            choices({'enabled': bool(enabled), 'directory': directory})
            db.execute('SELECT directory,cursor,manifest,copied_at,error,attempts,retry_at,inflight FROM targets LIMIT 0')
        sync_directory(self.root)
        self.instance = instance

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.root / 'archive.sqlite3', timeout=1)
        try:
            with db:
                yield db
        finally:
            db.close()

    def config(self, db):
        enabled, directory = db.execute('SELECT enabled,directory FROM settings WHERE id=1').fetchone()
        return {'enabled': bool(enabled), 'directory': directory}

    def save(self, value, expected):
        value = choices(value)
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if expected != revision(self.config(db)):
                raise ArchiveConflict('archive_config_changed')
            db.execute('UPDATE settings SET enabled=?,directory=? WHERE id=1', (value['enabled'], value['directory']))
            if value['directory']:
                db.execute('INSERT OR IGNORE INTO targets(directory) VALUES(?)', (value['directory'],))
        self.wake.set()
        return self.status()

    def retry(self, expected):
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            config = self.config(db)
            if expected != revision(config):
                raise ArchiveConflict('archive_config_changed')
            if self.active:
                raise ValueError('archive_busy')
            db.execute('UPDATE targets SET error=NULL,attempts=0,retry_at=0 WHERE directory=?', (config['directory'],))
        self.wake.set()
        return self.status()

    def status(self):
        # Never stat, resolve, open or enumerate the user-supplied NAS path here.
        with self.lock, self.connect() as db:
            config = self.config(db)
            target = db.execute('SELECT cursor,manifest,copied_at,error,attempts,retry_at,inflight FROM targets WHERE directory=?', (config['directory'],)).fetchone()
            active = bool(self.active)
            copying_current = active and self.active['directory'] == config['directory']
            stopping = active and self.active['timed_out']
        cursor, manifest, copied_at, error, attempts, retry_at, inflight = target or (0, None, None, None, 0, 0, None)
        with self.store.connect() as db:
            copied = db.execute('SELECT COUNT(*) FROM capture_events WHERE event_id<=?', (cursor,)).fetchone()[0]
            pending = db.execute('SELECT COUNT(*) FROM capture_events WHERE event_id>?', (cursor,)).fetchone()[0]
        state = ('disabled' if not config['enabled'] else 'waiting_for_worker' if stopping else 'copying' if copying_current else
                 'waiting_for_worker' if active else 'blocked' if error in PERMANENT_ERRORS else
                 'retrying' if error else 'pending' if pending else 'waiting_for_capture' if not cursor else 'ready')
        return {'state': state, 'config': config, 'revision': revision(config),
                'copied_events': copied, 'pending_events': pending, 'last_copied_at': copied_at,
                'last_manifest_sha256': manifest, 'error': error or self.last_error,
                'retry_at': retry_at if error and error not in PERMANENT_ERRORS else None,
                'in_progress': active, 'training_allowed': False, 'accuracy_verified': False}

    def next_request(self):
        with self.lock, self.connect() as db:
            config = self.config(db)
            if not config['enabled'] or self.active:
                return None
            cursor, error, retry_at = db.execute('SELECT cursor,error,retry_at FROM targets WHERE directory=?', (config['directory'],)).fetchone()
            if error in PERMANENT_ERRORS or retry_at > time.time():
                return None
            with self.store.connect() as captures:
                row = captures.execute('''SELECT e.event_id,f.camera,f.frame_id,f.captured_at,f.received_at,f.sha256,f.bytes,c.clock_id,c.monotonic_us
                    FROM capture_events e JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id
                    LEFT JOIN capture_clocks c ON c.camera=e.camera AND c.frame_id=e.frame_id
                    WHERE e.event_id>? ORDER BY e.event_id LIMIT 1''', (cursor,)).fetchone()
            if not row:
                return None
            event, camera, frame, captured, received, image_hash, image_bytes, clock, monotonic = row
            request = {'directory': config['directory'], 'source': str((self.store.root / 'images' / (image_hash + '.jpg')).absolute()),
                       'metadata': {'schema_version': 1, 'source_instance': self.instance, 'event_id': event,
                                    'camera_key': hashlib.sha256(camera.encode()).hexdigest(), 'frame_id': frame,
                                    'captured_at': captured, 'received_at': received, 'image_sha256': image_hash,
                                    'image_bytes': image_bytes, 'clock_id': clock, 'monotonic_us': monotonic,
                                    'training_allowed': False, 'accuracy_verified': False, 'split_status': 'unchecked'}}
            try:
                validate_request(request)
            except ValueError:
                self.record_error(db, config['directory'], 'archive_source_invalid')
                return None
            # Intent is durable before a child may publish bytes remotely.
            db.execute('UPDATE targets SET inflight=? WHERE directory=?', (event, config['directory']))
            return request

    def record_error(self, db, directory, code):
        attempts = db.execute('SELECT attempts FROM targets WHERE directory=?', (directory,)).fetchone()[0] + 1
        delay = min(900, 30 * 2 ** min(attempts-1, 5))
        db.execute('UPDATE targets SET error=?,attempts=?,retry_at=? WHERE directory=?', (code, attempts, time.time()+delay, directory))

    def launch(self, request_file, result_file):
        env = {key: value for key, value in os.environ.items() if key.upper() in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL')}
        return subprocess.Popen([sys.executable, str(Path(__file__).with_name('archive_copy.py')), str(request_file), str(result_file),
                                 str(self.root / 'copy.lock'), str(os.getpid())],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env=env, close_fds=True, **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}))

    def start(self, request):
        job = self.root / ('job-' + uuid.uuid4().hex)
        try:
            job.mkdir(mode=0o700)
            request_file, result_file = job / 'request.json', job / 'result.json'
            with request_file.open('xb') as stream:
                os.chmod(request_file, 0o600)
                stream.write(canonical(request)); stream.flush(); os.fsync(stream.fileno())
            sync_directory(job)
            process = self.launcher(request_file, result_file)
        except OSError:
            with self.connect() as db:
                self.record_error(db, request['directory'], 'archive_worker_failed')
            self.cleanup(job)
            return
        self.active = {'process': process, 'request': request, 'directory': request['directory'],
                       'job': job, 'result': result_file, 'deadline': time.monotonic() + self.deadline, 'timed_out': False}

    @staticmethod
    def cleanup(job):
        # Only our fixed, local per-job files. Never delete remote or capture data.
        for name in ('request.json', 'result.json'):
            try:
                (job / name).unlink()
            except FileNotFoundError:
                pass
        try:
            job.rmdir()
        except OSError:
            pass

    def finish(self, active):
        request = active['request']
        expected = revision(request['metadata'])
        code = 'archive_timeout' if active['timed_out'] else 'archive_worker_failed'
        result = None
        if not active['timed_out'] and active['process'].returncode == 0:
            try:
                with active['result'].open('rb') as stream:
                    raw = stream.read(4097)
                if len(raw) <= 4096:
                    value = json.loads(raw)
                    if isinstance(value, dict):
                        if value == {'state': 'copied', 'manifest_sha256': expected}:
                            result = value
                        elif set(value) == {'state', 'code'} and value['state'] == 'error' and value['code'] in ERRORS:
                            code = value['code']
            except (OSError, ValueError, UnicodeError, RecursionError):
                pass
        with self.connect() as db:
            if result:
                db.execute('UPDATE targets SET cursor=?,manifest=?,copied_at=?,error=NULL,attempts=0,retry_at=0,inflight=NULL WHERE directory=?',
                           (request['metadata']['event_id'], expected, now(), request['directory']))
            else:
                self.record_error(db, request['directory'], code)
        self.active = None
        self.cleanup(active['job'])

    def tick(self):
        with self.lock:
            if self.active:
                active = self.active
                if active['process'].poll() is not None:
                    self.finish(active)
                elif time.monotonic() >= active['deadline'] and not active['timed_out']:
                    active['timed_out'] = True
                    active['process'].kill()
                    with self.connect() as db:
                        self.record_error(db, active['directory'], 'archive_timeout')
                    # Keep this slot occupied until reaped, including kernel D-state.
                return
            request = self.next_request()
            if request:
                self.start(request)

    def run(self):
        try:
            while not self.stop.is_set():
                try:
                    self.tick(); self.last_error = None
                except (OSError, sqlite3.Error, ValueError):
                    self.last_error = 'archive_local_storage_unavailable'
                self.wake.wait(5 if self.last_error else .25 if self.active else 2)
                self.wake.clear()
        finally:
            with self.lock:
                if self.active and self.active['process'].poll() is None:
                    self.active['timed_out'] = True
                    try:
                        self.active['process'].kill()
                        self.active['process'].wait(timeout=1)
                    except (OSError, subprocess.TimeoutExpired):
                        pass
                if self.active and self.active['process'].poll() is not None:
                    try:
                        self.finish(self.active)
                    except (OSError, sqlite3.Error):
                        pass
