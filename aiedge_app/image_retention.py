"""Fixed local image retention. Measurement rows and their source digests are permanent."""
import re
import sqlite3
import threading

from capture import verified_image
from durable_file import sync_directory

RECENT_EVENTS = 500
DEVELOPMENT_IMAGES = 250
DIGEST = re.compile("[a-f0-9]{64}")
# Every use of a shared JPEG must qualify. A manual capture pins its image.
USES = """SELECT e.event_id, EXISTS(SELECT 1 FROM continuous_capture_outcomes o
            WHERE o.event_id=e.event_id AND o.outcome='committed')
          FROM frames f JOIN capture_events e USING(camera,frame_id) WHERE f.sha256=?"""


class ImageRetention:
    def __init__(self, store, archive, consumption=None):
        self.store = store
        self.archive = archive
        self.consumption = consumption
        self.stop = threading.Event()

    def pins(self):
        path = self.store.root / "retention-pins.txt"
        values = set(path.read_text(encoding="utf-8-sig").splitlines()) if path.exists() else set()
        if any(not DIGEST.fullmatch(v) for v in values):
            raise ValueError("retention pin list invalid")
        return values

    def candidates(self):
        pinned = self.pins()
        eligible = set()
        with self.store.connect() as db:
            head = db.execute("SELECT COALESCE(MAX(event_id),0) FROM capture_events").fetchone()[0]
            cutoff = head - RECENT_EVENTS
            if self.consumption is not None:
                cutoff = min(cutoff, self.consumption.status().get("event_id") or 0)
            pos = 0
            while pos < head and not self.stop.is_set():
                rows = db.execute("""SELECT e.event_id, f.sha256, f.training_allowed,
                    EXISTS(SELECT 1 FROM continuous_capture_outcomes o WHERE o.event_id=e.event_id AND o.outcome='committed'),
                    EXISTS(SELECT 1 FROM human_reviews h WHERE h.sha256=f.sha256),
                    EXISTS(SELECT 1 FROM retired_images r WHERE r.sha256=f.sha256)
                    FROM capture_events e JOIN frames f USING(camera,frame_id)
                    WHERE e.event_id>? AND e.event_id<=? ORDER BY e.event_id LIMIT 512""",(pos,head)).fetchall()
                if not rows:
                    break
                for event, image, training, ordinary, reviewed, retired in rows:
                    if retired:
                        continue
                    if not DIGEST.fullmatch(image):
                        raise ValueError("retention digest invalid")
                    if event > cutoff or training or not ordinary or reviewed:
                        pinned.add(image)
                    else:
                        eligible.add(image)
                pos = rows[-1][0]
        return cutoff, sorted(eligible - pinned)[DEVELOPMENT_IMAGES:]

    def retire(self, images, cutoff):
        # A committed intent survives power loss. Admission and review use the
        # same SQLite writer boundary. New captures can safely reuse a digest.
        with self.archive.lock, self.store.lock, self.store.connect() as db:
            db.execute("ATTACH DATABASE ? AS ar",(str(self.archive.root/"archive.sqlite3"),))
            db.execute("BEGIN IMMEDIATE")
            cursors = db.execute("SELECT MIN(cursor) FROM ar.targets WHERE inflight IS NOT NULL OR directory IN (SELECT directory FROM ar.settings WHERE enabled=1)").fetchone()[0]
            if cursors is not None:
                cutoff = min(cutoff, cursors)
            for image in images:
                uses = db.execute(USES,(image,)).fetchall()
                if not uses or any(event > cutoff or not ordinary for event,ordinary in uses):
                    continue
                if db.execute("SELECT 1 FROM human_reviews WHERE sha256=? LIMIT 1",(image,)).fetchone():
                    continue
                if db.execute("SELECT 1 FROM frames WHERE sha256=? AND training_allowed!=0 LIMIT 1",(image,)).fetchone():
                    continue
                path = self.store.root/"images"/(image+".jpg")
                if path.is_symlink() or (self.store.root/"references"/(image+".image")).exists():
                    continue
                verified_image(path,image)
                db.execute("INSERT OR IGNORE INTO retired_images VALUES(?,1)",(image,))
            db.commit()

    def finish_pending(self):
        with self.store.lock, self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT sha256 FROM retired_images WHERE pending=1 LIMIT 16").fetchall()
            for image, in rows:
                if not DIGEST.fullmatch(image):
                    raise ValueError("retirement intent invalid")
                (self.store.root/"images"/(image+".jpg")).unlink(missing_ok=True)
            if rows:
                sync_directory(self.store.root/"images")
                db.executemany("UPDATE retired_images SET pending=0 WHERE sha256=?",rows)
            return len(rows)

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

    def run(self):
        while not self.stop.is_set():
            try:
                self.sweep()
                self.store.retention_error = None
            except (OSError, ValueError, sqlite3.Error):
                self.store.retention_error = "image_retention_incomplete"
            self.stop.wait(30)
