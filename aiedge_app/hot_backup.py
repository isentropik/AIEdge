"""Supervisor backup hooks. Keep the normal data tree as the stopped-app fallback."""
from contextlib import ExitStack, closing, contextmanager
from hashlib import file_digest
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import time
import uuid

from durable_file import sync_directory

WORK = '.aiedge-backup-work'
SEALED = 'aiedge-rollback-v1'
STATE = 'aiedge-state'
GEN = '.restored-generation'
RESERVE = 512 * 1024**2 + 4 * 1024**2
IMMUTABLE = {'images', 'original-recovery', 'references', 'recovery'}


def checksum(path):
    with path.open('rb') as f:
        return file_digest(f, 'sha256').hexdigest()


@contextmanager
def serialized(root):
    work = root / WORK
    work.mkdir(mode=0o700, exist_ok=True)
    with (work / 'lock').open('ab') as f:
        if os.name == 'posix':
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX)
        yield work


def durable_text(path, value):
    temp = path.with_suffix('.tmp')
    with temp.open('w', encoding='utf8') as f:
        f.write(value)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)
    sync_directory(path.parent)


def identity(path):
    s = path.stat(follow_symlinks=False)
    return s.st_ino, s.st_size, s.st_mtime_ns


def inventory(root):
    directories, mutable, originals, databases = {}, {}, [], []
    def raise_error(error):
        raise error
    for parent, _, files in os.walk(root, onerror=raise_error):
        directory = Path(parent)
        if directory.is_symlink() or any(p.is_symlink() for p in directory.iterdir()):
            raise ValueError('symlink in app state')
        directories[directory] = identity(directory)
        for name in files:
            p = directory / name
            if name == GEN or name.endswith(('.tmp', '-wal', '-journal', '-shm')):
                continue
            if not p.is_file():
                raise ValueError('unexpected special file in app state')
            rel = p.relative_to(root)
            if rel.parts[0] in IMMUTABLE:
                originals.append(rel)
            elif name.endswith('.sqlite3'):
                databases.append(rel)
            else:
                with p.open('rb') as f:
                    is_db = f.read(16) == b'SQLite format 3\x00'
                if is_db:
                    databases.append(rel)
                else:
                    mutable[rel] = identity(p)
    return directories, mutable, originals, sorted(databases)


def free_for(path, size):
    if shutil.disk_usage(path).free < size + RESERVE:
        raise OSError('insufficient space for backup and capture reserve')


def pin_original(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except FileNotFoundError:
        raise
    except OSError:
        free_for(dst.parent, src.stat().st_size)
        shutil.copyfile(src, dst)


class Changed(Exception):
    pass


def settled_capture(db):
    latest = db.execute('SELECT attempt_id FROM continuous_capture_attempts ORDER BY rowid DESC LIMIT 1').fetchone()
    return not latest or db.execute('SELECT 1 FROM continuous_capture_outcomes WHERE attempt_id=?',latest).fetchone() is not None


def snapshot(source, dest, on_cut=None):
    db_names = inventory(source)[3]
    with ExitStack() as readers:
        views = {}
        for rel in db_names:
            db = readers.enter_context(closing(sqlite3.connect((source/rel).as_uri()+'?mode=rw', uri=True, timeout=.1)))
            if db.execute('PRAGMA journal_mode=WAL').fetchone() != ('wal',):
                raise ValueError('unable to pin database without blocking capture')
            # Keep WAL and SHM handles open during the file inventory.
            db.execute('SELECT count(*) FROM sqlite_schema').fetchone()
            views[rel] = db
        capture = views[Path('captures.sqlite3')]
        if not settled_capture(capture):
            raise Changed()
        dirs, mutable, originals, found = inventory(source)
        if found != db_names:
            raise Changed()
        free_for(dest, sum((source/p).stat().st_size for p in db_names))
        for d in dirs:
            (dest / d.relative_to(source)).mkdir(parents=True, exist_ok=True)
        for rel in originals:
            pin_original(source/rel, dest/rel)
        for rel in mutable:
            shutil.copyfile(source/rel, dest/rel)
        with ExitStack() as writers:
            for rel in db_names:
                db = writers.enter_context(closing(sqlite3.connect((source/rel).as_uri()+'?mode=rw', uri=True, timeout=0)))
                db.execute('BEGIN IMMEDIATE')
            for db in views.values():
                db.execute('BEGIN')
                db.execute('SELECT count(*) FROM sqlite_schema').fetchone()
            if not settled_capture(capture) or any(identity(d) != old for d, old in dirs.items()) or any(identity(source/p) != old for p, old in mutable.items()):
                raise Changed()
        if on_cut:
            on_cut()
        for rel, db in views.items():
            with closing(sqlite3.connect(dest / rel)) as out:
                db.backup(out, pages=256, progress=lambda *_: free_for(dest, 0))
                out.execute('PRAGMA journal_mode=DELETE')
    # A shared inode becomes a tar hard link. Supervisor reads encrypted members
    # as a forward-only stream and cannot seek back to extract that link.
    # Retain the pins until the database cut is durable, then detach them with
    # the database locks released so capture can continue throughout the copy.
    scratch = dest.parent / 'detached-original'
    for rel in originals:
        pinned = dest / rel
        info = pinned.stat()
        if info.st_nlink > 1:
            free_for(dest, info.st_size)
            shutil.copyfile(pinned, scratch)
            os.replace(scratch, pinned)
    return db_names


def check(data, manifest):
    paths = {p.relative_to(data).as_posix() for p in data.rglob('*') if p.is_file() and p.name != GEN}
    if paths != set(manifest['files']):
        raise ValueError('rollback file list mismatch')
    for name, expected in manifest['files'].items():
        path = data / name
        if path.is_symlink() or checksum(path) != expected:
            raise ValueError('rollback hash mismatch: '+name)
        if path.parent.name in {'images','references','original-recovery'} and path.suffix in {'.image','.jpg'} and path.stem != expected:
            raise ValueError('content-addressed file mismatch')
    for name in manifest['databases']:
        if name not in paths:
            raise ValueError('missing rollback database')
        with closing(sqlite3.connect((data/name).as_uri()+'?mode=ro&immutable=1', uri=True)) as db:
            if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)] or db.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('rollback database invalid: '+name)
            if name != 'captures.sqlite3':
                continue
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            compact = 'AND NOT EXISTS (SELECT 1 FROM compact_exposures c WHERE c.event_id=e.event_id)' if 'compact_exposures' in tables else ''
            photos = db.execute('SELECT DISTINCT f.sha256 FROM frames f JOIN capture_events e USING(camera,frame_id) '
                                'WHERE NOT EXISTS (SELECT 1 FROM retired_images r WHERE r.sha256=f.sha256) '+compact)
            if any(f'images/{sha}.jpg' not in paths for sha, in photos):
                raise ValueError('ledger photo missing')
            if 'original_receipts' in tables:
                for sha, event in db.execute('SELECT DISTINCT sha,event_id FROM original_receipts r WHERE NOT EXISTS '
                                             '(SELECT 1 FROM retired_images i WHERE i.sha256=r.sha)'):
                    folder = 'original-recovery' if event is None else 'images'
                    if f'{folder}/{sha}.jpg' not in paths:
                        raise ValueError('receipted original missing')
    config = data / 'calibration.json'
    if config.is_file():
        ref = json.loads(config.read_bytes()).get('reference_sha256')
        if ref and f'references/{ref}.image' not in paths:
            raise ValueError('calibration reference missing')


def prepare(root, on_cut=None):
    with serialized(root) as work:
        source = root / STATE
        if not (source/'captures.sqlite3').is_file():
            raise ValueError('capture store unavailable for hot backup')
        # A failed hook must never leave an old sealed generation available.
        cleanup(root, work)
        temp = work/'building'
        try:
            deadline = time.monotonic()+45
            while True:
                if temp.exists():
                    shutil.rmtree(temp)
                data = temp/'state'
                data.mkdir(parents=True)
                try:
                    dbs = snapshot(source, data, on_cut)
                    break
                except (Changed, FileNotFoundError, sqlite3.OperationalError) as exc:
                    if isinstance(exc, sqlite3.OperationalError) and exc.sqlite_errorcode not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                        raise
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(.25)
            generation = uuid.uuid4().hex
            manifest = dict(version=1, generation=generation, databases=[p.as_posix() for p in dbs],
                            files={p.relative_to(data).as_posix():checksum(p) for p in data.rglob('*') if p.is_file()})
            check(data, manifest)
            durable_text(temp/'manifest.json', json.dumps(manifest, separators=(',',':')))
            durable_text(work/'owner', generation)
            os.replace(temp, root/SEALED)
            sync_directory(root)
            return generation
        finally:
            if temp.exists():
                shutil.rmtree(temp)


def cleanup(root, work):
    sealed = root / SEALED
    if sealed.exists():
        if not (work/'owner').is_file() or (work/'owner').read_text() != json.loads((sealed/'manifest.json').read_bytes())['generation']:
            raise ValueError('unapplied restore cannot be discarded')
        # Removing the sealed marker first also makes cleanup restartable.
        discard = work/'discard'
        if discard.exists():
            shutil.rmtree(discard)
        os.replace(sealed, discard)
        sync_directory(root)
        shutil.rmtree(discard)
    (work/'owner').unlink(missing_ok=True)


def startup(root):
    root.mkdir(exist_ok=True, parents=True)
    with serialized(root) as work:
        state, sealed = root/STATE, root/SEALED
        if sealed.exists():
            manifest = json.loads((sealed/'manifest.json').read_bytes())
            gen = manifest['generation']
            if manifest.get('version') != 1 or not isinstance(gen,str) or not re.fullmatch('[0-9a-f]{32}',gen):
                raise ValueError('invalid rollback manifest')
            owner = work/'owner'
            if not owner.exists() or owner.read_text() != gen:
                if not (state/GEN).is_file() or (state/GEN).read_text() != gen:
                    staged = sealed/'state'
                    check(staged, manifest)
                    durable_text(staged/GEN, gen)
                    if state.exists():
                        os.replace(state, work/('before-'+gen))
                        sync_directory(root)
                    os.replace(staged, state)
                    sync_directory(root)
                durable_text(owner, gen)
            cleanup(root, work)
            old = work/('before-'+gen)
            if old.exists():
                shutil.rmtree(old)
        state.mkdir(exist_ok=True)
        # First run after a dev158 update or a restore of its native layout.
        for item in root.iterdir():
            if item.name in {STATE, WORK, SEALED, 'options.json','lost+found'}:
                continue
            if (state/item.name).exists():
                raise ValueError('legacy data collision: '+item.name)
            os.replace(item, state/item.name)
        sync_directory(state)
        sync_directory(root)
        return state


if __name__ == '__main__':
    root = Path('/data')
    if sys.argv[1:] == ['prepare']:
        print('Sealed AIEdge rollback', prepare(root), flush=True)
    elif sys.argv[1:] == ['finish']:
        with serialized(root) as work:
            cleanup(root, work)
    else:
        raise SystemExit(2)
