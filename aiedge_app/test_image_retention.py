import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from archive import Archive
from capture import Store
from image_retention import ImageRetention
from review_store import Reviews
from test_capture import headers


class ImageRetentionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = Store(self.root)
        self.archive = Archive(self.store)
        Reviews(self.store,None)
        self.worker = ImageRetention(self.store,self.archive)
        self.blobs = {}
        for event in range(1,13):
            blob = b"\xff\xd8"+bytes([event])+b"\xff\xd9"
            digest = hashlib.sha256(blob).hexdigest()
            self.blobs[digest] = (event,blob)
            self.store.add("fixture",blob,headers(str(event),blob))
            if event != 5:
                with self.store.connect() as db:
                    db.execute("INSERT INTO continuous_capture_outcomes VALUES(?,'committed',?,NULL,'test')",(str(event),event))
        self.recent = patch("image_retention.RECENT_EVENTS",2)
        self.dev = patch("image_retention.DEVELOPMENT_IMAGES",1)
        self.recent.start();self.dev.start()
        self.addCleanup(self.recent.stop);self.addCleanup(self.dev.stop)

    def test_expiry_restart_redelivery_and_recapture(self):
        protected = list(self.blobs)[0]
        (self.root/"retention-pins.txt").write_text(protected)
        with self.store.connect() as db:
            db.execute("INSERT INTO human_reviews VALUES(1,?,'context','revision','{}')",(list(self.blobs)[1],))
        cutoff, candidates=self.worker.candidates()
        self.worker.retire(candidates,cutoff)
        restarted=ImageRetention(Store(self.root),self.archive)
        restarted.finish_pending()
        self.assertEqual(len(list((self.root/"images").glob("*.jpg"))),6)
        self.assertEqual(len(self.store.history()["items"]),12)
        self.assertEqual(self.store.image(protected),self.blobs[protected][1])
        digest=candidates[0];event,blob=self.blobs[digest]
        self.assertFalse(self.store.add("fixture",blob,headers(str(event),blob)))
        with self.assertRaises(FileNotFoundError):self.store.image(digest)
        self.assertTrue(self.store.add("fixture",blob,headers("new",blob)))
        self.assertEqual(self.store.image(digest),blob)

    def test_archive_backlog_and_later_archive(self):
        cutoff,candidates=self.worker.candidates()
        self.archive.save(dict(enabled=True,directory="/media/first"),self.archive.status()["revision"])
        self.worker.retire(candidates,cutoff)
        self.assertEqual(self.worker.finish_pending(),0)
        self.archive.save(dict(enabled=False,directory=""),self.archive.status()["revision"])
        self.worker.sweep()
        self.archive.save(dict(enabled=True,directory="/media/later"),self.archive.status()["revision"])
        with self.archive.connect() as db:
            db.execute("UPDATE targets SET cursor=? WHERE directory='/media/later'",(self.blobs[candidates[0]][0]-1,))
        self.assertIsNone(self.archive.next_request())
        self.assertGreater(self.archive.status()["expired_before_archive"],0)
