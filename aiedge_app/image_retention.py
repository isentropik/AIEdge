"""Fixed local image retention. Measurement rows and their source digests are permanent."""
import hashlib
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone

from capture import verified_image
from durable_file import sync_directory
from gap_images import older_keep
from retention_history import RetentionHistory, digest_bucket, version
from retention_settings import read as read_settings, save as save_settings
from reviewed_photo import NAME as REVIEW_FILE

RECENT_EVENTS = 500
DEVELOPMENT_IMAGES = 250
DIGEST = re.compile("[a-f0-9]{64}")


class SelectionChanged(Exception):
    """Protection inputs changed while a retention decision was being prepared."""


def identity(path):
    try:
        st = path.lstat()
        return st.st_dev, st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns, st.st_ctime_ns
    except FileNotFoundError:
        return None


def archive_cursor(db):
    return db.execute("SELECT MIN(cursor) FROM ar.targets WHERE inflight IS NOT NULL OR directory IN "
                      "(SELECT directory FROM ar.settings WHERE enabled=1)").fetchone()[0]


class ImageRetention:
    def __init__(self, store, archive, consumption=None, photo_register=None, reading_format=None):
        self.store = store
        self.archive = archive
        self.consumption = consumption
        self.photo_register = photo_register
        self.reading_format = reading_format
        self.stop = threading.Event()
        self.history = RetentionHistory()
        self.plan_lock = threading.Lock()
        self.image_facts = {}
        self.fact_versions = {}
        self.fact_schema = None

    def settings(self):
        with self.store.lock:
            result = read_settings(self.store.root)
            result['evidence'] = getattr(self.store, 'retention_evidence', None)
            result['error'] = getattr(self.store, 'retention_error', None)
            return result

    def save_settings(self, config, revision):
        with self.archive.lock, self.store.lock:
            return save_settings(self.store.root, config, revision)

    def _preserve_original_dials(self, document, digest, image):
        from original_dials import preserve
        return preserve(self.store, self.reading_format.recognition, self.photo_register, document, digest, image)

    def recover_chart_photo(self, image):
        """Recover numeric evidence from a matching, already expired original."""
        from hourly_photo import preserve_photo
        if self.photo_register is None or self.reading_format is None:
            raise ValueError('photo_reader_unavailable')
        digest=hashlib.sha256(image).hexdigest()
        with self.store.connect() as db:
            if not db.execute('SELECT 1 FROM retired_images WHERE sha256=? AND pending=0',(digest,)).fetchone():
                raise ValueError('no_matching_expired_photo')
        document=self.reading_format.status()['format']
        if not document or document['unit']!='ft3':
            raise ValueError('gas_reading_format_unavailable')
        count=preserve_photo(self.store,self.photo_register,document,digest,image)
        supported=self._preserve_original_dials(document,digest,image)
        if not count and not supported:
            raise ValueError('photo_has_no_supported_register')
        return dict(source_sha256=digest,verified_anchors=count,meter_evidence=supported)

    def recent_events(self):
        saved = read_settings(self.store.root)
        return saved['config']['recent_events'] if saved['revision'] != 'default' else RECENT_EVENTS

    def pins(self):
        path = self.store.root / "retention-pins.txt"
        values = set(path.read_text(encoding="utf-8-sig").splitlines()) if path.exists() else set()
        if any(not DIGEST.fullmatch(v) for v in values):
            raise ValueError("retention pin list invalid")
        # Reviewed photo constraints are explicit protected evidence. A malformed
        # manifest stops retirement through the existing fail-closed error path.
        from reviewed_photo import load
        values.update(r['source_sha256'] for r in load(self.store.root))
        return values

    def file_version(self):
        return tuple(identity(self.store.root/name) for name in (
            'images', 'references', 'retention-pins.txt', REVIEW_FILE, 'image-retention.json'))

    def _refresh_images(self, db, files):
        revisions = dict(db.execute('SELECT page,revision FROM retention_pages WHERE page<=-2'))
        facts = self.image_facts
        if self.fact_schema!=self.history.schema or self.fact_versions.get(-2)!=revisions.get(-2):
            facts = {}
        changed = [image for image in files if image not in facts or
                   self.fact_versions.get(digest_bucket(image))!=revisions.get(digest_bucket(image))]
        current = {image:facts[image] for image in files if image in facts}
        for offset in range(0,len(changed),128):
            batch = changed[offset:offset+128]
            current.update(dict.fromkeys(batch))
            placeholders = ','.join('?' for _ in batch)
            rows = db.execute(f"""SELECT e.event_id, f.sha256, f.bytes, f.training_allowed,
                EXISTS(SELECT 1 FROM continuous_capture_outcomes o WHERE o.event_id=e.event_id AND o.outcome='committed'),
                EXISTS(SELECT 1 FROM human_reviews h WHERE h.sha256=f.sha256),
                EXISTS(SELECT 1 FROM retired_images r WHERE r.sha256=f.sha256 AND r.pending=0)
                FROM frames f LEFT JOIN capture_events e USING(camera,frame_id)
                WHERE f.sha256 IN ({placeholders})""",batch).fetchall()
            for event,image,size,training,ordinary,reviewed,retired in rows:
                maximum, latest, protect = current[image] or (0,None,False)
                if event is not None and not retired:
                    if not DIGEST.fullmatch(image):
                        raise ValueError("retention digest invalid")
                    latest = event if latest is None else max(latest,event)
                    protect = protect or training or not ordinary or reviewed
                current[image] = max(size,maximum),latest,protect
        self.image_facts, self.fact_versions, self.fact_schema = current, revisions, self.history.schema

    def _selection(self, db, cutoff, evidence, report):
        pinned = self.pins()
        eligible = set()
        sizes = {}
        with os.scandir(self.store.root/'images') as listing:
            files = {f.name[:-4] for f in listing if f.name.endswith('.jpg') and len(f.name)>=6 and f.is_file(follow_symlinks=False)}
        try:
            with os.scandir(self.store.root/'references') as listing:
                references = {f.name[:-6] for f in listing if f.name.endswith('.image') and os.path.exists(f.path)}
        except FileNotFoundError:
            references = set()
        self._refresh_images(db,files)
        for image,facts in self.image_facts.items():
            if facts is None:
                continue
            sizes[image],latest,protect = facts
            if latest is not None:
                if latest>cutoff or protect or image in references:
                    pinned.add(image)
                else:
                    eligible.add(image)
        present = (eligible | pinned).intersection(files)
        settings = read_settings(self.store.root)
        config = settings['config']
        # Existing gap evidence never competes with discretionary development photos.
        # Keep a surviving endpoint even when its counterpart was already lost.
        gap_members = {s for _,_,pair in evidence for s in pair} & present
        pinned.update(gap_members)
        slots = config['older_images'] if settings['revision'] != 'default' else DEVELOPMENT_IMAGES
        keep = older_keep(db, eligible & present, pinned & present, slots,
                          byte_limit=config['older_megabytes'] * 1024**2, report=report, evidence=evidence, sizes=sizes)
        if report is not None:
            report.update(protected_gap_images=len(gap_members),
                          protected_gap_bytes=sum(sizes[s] for s in gap_members),
                          present_images=len(present), present_bytes=sum(sizes[s] for s in present),
                          policy='preserve_existing_gap_endpoints', settings_revision=settings['revision'])
        return (eligible & present) - pinned - keep

    def _plan(self, db, limit=None, archive=False, report=None):
        with self.plan_lock:
            return self._read_plan(db,limit,archive,report)

    def _read_plan(self, db, limit, archive, report):
        consumed = (self.consumption.status().get("event_id") or 0) if self.consumption is not None else None
        if archive:
            db.execute('ATTACH DATABASE ? AS ar',(str(self.archive.root/'archive.sqlite3'),))
        for _ in range(3):
            token,head,gaps = self.history.snapshot(db)
            files = self.file_version()
            cutoff = head - self.recent_events()
            cursor = archive_cursor(db) if archive else None
            for bound in (limit, consumed, cursor):
                if bound is not None:
                    cutoff = min(cutoff,bound)
            allowed = self._selection(db,cutoff,gaps,report)
            if token==version(db) and files==self.file_version():
                return cutoff,allowed,(token,files,cursor)
        raise SelectionChanged()

    def _candidates(self, db, cutoff, report=None):
        return sorted(self._plan(db,cutoff,report=report)[1])

    def candidates(self):
        with self.store.connect() as db:
            cutoff,allowed,_ = self._plan(db)
            return cutoff,sorted(allowed)

    def _current(self, db, stamp):
        return stamp==(version(db),self.file_version(),archive_cursor(db))

    def _protected(self, db, image, cutoff):
        if (self.store.root/'references'/(image+'.image')).exists():
            return True
        return db.execute("""SELECT 1 FROM frames f JOIN capture_events e USING(camera,frame_id)
            WHERE f.sha256=? AND (e.event_id>? OR NOT EXISTS
            (SELECT 1 FROM continuous_capture_outcomes o WHERE o.event_id=e.event_id AND o.outcome='committed'))
            UNION ALL SELECT 1 FROM frames WHERE sha256=? AND training_allowed!=0
            UNION ALL SELECT 1 FROM human_reviews WHERE sha256=? LIMIT 1""",(image,cutoff,image,image)).fetchone() is not None

    def retire(self, images, cutoff):
        # A committed intent survives power loss. Admission and review use the
        # same SQLite writer boundary. New captures can safely reuse a digest.
        with self.store.connect() as db:
            cutoff,allowed,stamp = self._plan(db,cutoff,archive=True)
            verified = {}
            for image in allowed.intersection(images):
                path = self.store.root/"images"/(image+".jpg")
                before = identity(path)
                blob = verified_image(path,image)
                if self.photo_register is not None:
                    document = self.reading_format.status()['format']
                    if document and document['unit']=='ft3':
                        self._preserve_original_dials(document,image,blob)
                verified[image] = before
            with self.archive.lock,self.store.lock:
                db.execute('BEGIN IMMEDIATE')
                if self._current(db,stamp):
                    for image,before in verified.items():
                        if (before is not None and before==identity(self.store.root/'images'/(image+'.jpg'))
                                and not self._protected(db,image,cutoff)):
                            db.execute('INSERT OR IGNORE INTO retired_images VALUES(?,1)',(image,))
                db.commit()

    def finish_pending(self):
        # Read and fit outside the capture and archive writer locks. Only delete
        # intents examined in this batch, and recheck them under the writer lock.
        with self.store.connect() as db:
            pending = [r[0] for r in db.execute("SELECT sha256 FROM retired_images WHERE pending=1 LIMIT 16")]
        if not pending:
            return 0
        if self.photo_register is not None:
            from hourly_photo import preserve_photo
            document=self.reading_format.status()['format']
            if document and document['unit']=='ft3':
                for digest in pending:
                    if not DIGEST.fullmatch(digest):
                        raise ValueError("retirement intent invalid")
                    path=self.store.root/'images'/(digest+'.jpg')
                    if path.is_file() and not path.is_symlink():
                        blob = verified_image(path,digest)
                        preserve_photo(self.store,self.photo_register,document,digest,blob)
                        # Also repair an intent left pending by an earlier version.
                        self._preserve_original_dials(document,digest,blob)
        with self.store.connect() as db:
            cutoff,allowed,stamp = self._plan(db,archive=True)
            with self.archive.lock,self.store.lock:
                db.execute('BEGIN IMMEDIATE')
                if not self._current(db,stamp):
                    db.rollback()
                    return 0
                completed = []
                for image in pending:
                    if not DIGEST.fullmatch(image):
                        raise ValueError("retirement intent invalid")
                    if not db.execute('SELECT 1 FROM retired_images WHERE sha256=? AND pending=1',(image,)).fetchone():
                        continue
                    path = self.store.root/'images'/(image+'.jpg')
                    if path.is_symlink() or (path.exists() and (image not in allowed or self._protected(db,image,cutoff))):
                        db.execute('DELETE FROM retired_images WHERE sha256=? AND pending=1',(image,))
                    else:
                        path.unlink(missing_ok=True)
                        completed.append((image,))
                if completed:
                    sync_directory(self.store.root/'images')
                    db.executemany('UPDATE retired_images SET pending=0 WHERE sha256=?',completed)
                db.commit()
                return len(pending)

    def sweep(self):
        while self.finish_pending() and not self.stop.is_set():
            pass
        cutoff, candidates = self.candidates()
        for start in range(0,len(candidates),16):
            if self.stop.is_set():
                return
            self.retire(candidates[start:start+16],cutoff)
            self.finish_pending()
            self.stop.wait(.02)
        # Publish a timestamped selection audit, not a promise about all history.
        # Protected/recent images remain outside the older automatic pool.
        report = {'checked_at':datetime.now(timezone.utc).isoformat(),
                  'recent_events':self.recent_events(), 'protected_exceptions':True}
        with self.store.connect() as db:
            self._candidates(db, cutoff, report)
        self.store.retention_evidence = report

    def run(self):
        while not self.stop.is_set():
            try:
                self.sweep()
                self.store.retention_error = None
            except SelectionChanged:
                pass  # Re-evaluate the pending work on the next sweep.
            except (OSError, ValueError, sqlite3.Error):
                self.store.retention_error = "image_retention_incomplete"
            self.stop.wait(30)
