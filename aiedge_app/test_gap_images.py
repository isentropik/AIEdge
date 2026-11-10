import unittest
from unittest.mock import patch
from test_image_retention import ImageRetentionTests
from gap_images import gap_pairs, older_keep
from image_retention import ImageRetention


class GapImagesTests(unittest.TestCase):
    def setUp(self):
        ImageRetentionTests.setUp(self)
        self.dev.stop()
        self.dev = patch('image_retention.DEVELOPMENT_IMAGES',4)
        self.dev.start()
        self.addCleanup(self.dev.stop)
        self.images = list(self.blobs)

    def fail_after(self, event):
        with self.store.connect() as db:
            db.execute("INSERT INTO capture_failure_boundaries VALUES(?,?,'camera_timeout','unknown')",(event,event))

    def test_exact_54_second_interval_preserves_both(self):
        with self.store.connect() as db:
            db.execute('UPDATE capture_clocks SET monotonic_us=monotonic_us+44179274 WHERE CAST(frame_id AS INTEGER)>=8')
        with patch('image_retention.DEVELOPMENT_IMAGES',2):
            self.worker.sweep()
        for i in (6,7):
            self.assertEqual(self.store.image(self.images[i]),self.blobs[self.images[i]][1])

    def test_failure_kept_after_restart_without_clock_delay(self):
        self.fail_after(7)
        ImageRetention(self.store,self.archive).sweep()
        for i in (6,7): self.assertTrue((self.root/'images'/(self.images[i]+'.jpg')).exists())

    def test_pending_attempt_then_first_success(self):
        with self.store.connect() as db:
            db.execute("INSERT INTO continuous_capture_attempts VALUES('pending',1,7,'test')")
            self.assertIn((self.images[6],self.images[7]),gap_pairs(db))

    def test_open_gap_protects_last_image(self):
        self.fail_after(12)
        with self.store.connect() as db:
            self.assertIn((self.images[11],self.images[11]),gap_pairs(db))

    def test_latest_pairs_win_and_do_not_split_for_one_slot(self):
        for e in (2,6,8): self.fail_after(e)
        with self.store.connect() as db:
            eligible=set(self.images[:10])
            keep=older_keep(db,eligible,set(),3)
            self.assertTrue(set(self.images[7:9])<=keep)
            self.assertFalse(set(self.images[5:7])&keep)
            self.assertLessEqual(len(keep),3)

    def test_byte_cap_atomic_pair_and_shared_digest(self):
        self.fail_after(7)
        with self.store.connect() as db:
            eligible=set(self.images)
            keep=older_keep(db,eligible,set(),250,byte_limit=9)
            self.assertFalse(set(self.images[6:8])&keep)
            self.assertLessEqual(sum(len(self.blobs[x][1]) for x in keep),9)
            db.execute("UPDATE frames SET sha256=? WHERE frame_id='8'",(self.images[6],))
            eligible.discard(self.images[7])
            keep=older_keep(db,eligible,set(),1,byte_limit=5)
            self.assertEqual(keep,{self.images[6]})

    def test_gap_arrives_after_candidate_selection(self):
        cutoff,candidates=self.worker.candidates()
        event=self.blobs[candidates[0]][0]
        self.fail_after(event)
        self.worker.retire(candidates,cutoff)
        self.worker.finish_pending()
        self.assertTrue((self.root/'images'/(candidates[0]+'.jpg')).exists())

    def test_gap_arrives_after_intent_before_unlink(self):
        cutoff,candidates=self.worker.candidates()
        image=candidates[0]
        self.worker.retire([image],cutoff)
        self.fail_after(self.blobs[image][0])
        self.worker.finish_pending()
        self.assertTrue((self.root/'images'/(image+'.jpg')).exists())
        with self.store.connect() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM retired_images WHERE sha256=?',(image,)).fetchone())

    def test_new_pin_after_intent_cancels_delete(self):
        cutoff,candidates=self.worker.candidates()
        image=candidates[0]
        self.worker.retire([image],cutoff)
        (self.root/'retention-pins.txt').write_text(image)
        self.worker.finish_pending()
        self.assertTrue((self.root/'images'/(image+'.jpg')).exists())

    def test_gap_ledger_unchanged_and_old_deleted_not_resurrected(self):
        self.worker.sweep()
        with self.store.connect() as db:
            expired=db.execute('SELECT sha256 FROM retired_images WHERE pending=0 LIMIT 1').fetchone()[0]
        self.fail_after(self.blobs[expired][0])
        with self.store.connect() as db:
            before=db.execute('SELECT * FROM capture_failure_boundaries').fetchall()
        self.worker.sweep()
        with self.store.connect() as db:
            self.assertEqual(before,db.execute('SELECT * FROM capture_failure_boundaries').fetchall())
            self.assertEqual(db.execute('SELECT COUNT(*) FROM capture_events').fetchone()[0],12)
        self.assertFalse((self.root/'images'/(expired+'.jpg')).exists())

    def test_clock_break_and_segment_boundary(self):
        with self.store.connect() as db:
            db.execute("UPDATE capture_clocks SET clock_id='other' WHERE frame_id='7'")
            db.execute('CREATE TABLE consumption_segment_links(first_event INTEGER)')
            db.execute('INSERT INTO consumption_segment_links VALUES(3)')
            pairs=gap_pairs(db)
        self.assertIn(tuple(self.images[5:7]),pairs)
        self.assertIn(tuple(self.images[1:3]),pairs)

    def test_rejected_readings_preserve_accepted_bracket(self):
        with self.store.connect() as db:
            db.execute('CREATE TABLE consumption_records(event_id INTEGER,result TEXT)')
            db.executemany('INSERT INTO consumption_records VALUES(?,?)',[(i,'{"observation_accepted":'+('true' if i in (1,2,8,9) else 'false')+'}') for i in range(1,10)])
            self.assertIn((self.images[1],self.images[7]),gap_pairs(db))

    def test_pool_cap_under_many_gaps(self):
        for event in range(1,11): self.fail_after(event)
        self.worker.sweep()
        with self.store.connect() as db:
            remaining=db.execute('SELECT COUNT(DISTINCT f.sha256) FROM frames f JOIN capture_events e USING(camera,frame_id) WHERE e.event_id<=10 AND e.event_id!=5 AND NOT EXISTS(SELECT 1 FROM retired_images r WHERE r.sha256=f.sha256)').fetchone()[0]
        self.assertEqual(remaining,9)  # Protected gap endpoints no longer compete for four ordinary slots.
        self.assertEqual(self.store.retention_evidence['budget_excluded_pairs'],0)
        self.assertLessEqual(self.store.retention_evidence['selected_older_images'],4)

    def test_archive_enabled_after_intent_preserves_photo(self):
        cutoff,candidates=self.worker.candidates()
        image=candidates[0]
        self.worker.retire([image],cutoff)
        self.archive.save(dict(enabled=True,directory='/media/new'),self.archive.status()['revision'])
        self.worker.finish_pending()
        self.assertTrue((self.root/'images'/(image+'.jpg')).exists())

    def test_accounting_recovery_after_intent_preserves_photo(self):
        from types import SimpleNamespace
        cutoff,candidates=self.worker.candidates()
        image=candidates[0]
        self.worker.retire([image],cutoff)
        self.worker.consumption=SimpleNamespace(status=lambda: {'event_id':0})
        self.worker.finish_pending()
        self.assertTrue((self.root/'images'/(image+'.jpg')).exists())
