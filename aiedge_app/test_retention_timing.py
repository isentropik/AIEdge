"""Regression checks for incremental retention and races with new protection evidence."""
import unittest
from unittest.mock import patch

import test_image_retention as fixtures
from gap_images import gap_pairs
from test_capture import headers


class RetentionTimingTests(unittest.TestCase):
    def setUp(self):
        fixtures.ImageRetentionTests.setUp(self)
        page = patch('retention_history.PAGE', 4)
        page.start()
        self.addCleanup(page.stop)

    def assert_same_gaps(self):
        with self.store.connect() as db:
            _, _, actual = self.worker.history.snapshot(db)
            self.assertEqual(actual, gap_pairs(db, with_events=True))
            return actual

    def test_warm_sweep_and_tail_append(self):
        history = self.worker.history
        with patch.object(history, '_block', wraps=history._block) as scan:
            self.assert_same_gaps()
            self.assertEqual(scan.call_count, 3)
            scan.reset_mock()
            self.assert_same_gaps()
            self.assertEqual(scan.call_count, 0)
            photo = b'\xff\xd8\x0d\xff\xd9'
            self.store.add('fixture', photo, headers('13', photo))
            self.assertTrue(self.assert_same_gaps())
            self.assertEqual(scan.call_count, 2)

    def test_old_edits_replacements_and_open_gap_match_full_scan(self):
        with self.store.connect() as db:
            db.execute('CREATE TABLE consumption_records(segment_id TEXT,event_id INTEGER,result TEXT,'
                       'PRIMARY KEY(segment_id,event_id))')
            db.executemany('INSERT INTO consumption_records VALUES(?,?,?)', [
                ('a', 2, '{"observation_accepted":true}'), ('a', 9, '{"observation_accepted":false}'),
                ('b', 4, '{"observation_accepted":true}'), ('b', 5, '{"observation_accepted":true}')])
        self.assertTrue(self.assert_same_gaps())
        mutations = [
            ("INSERT INTO capture_failure_boundaries VALUES(1,12,'timeout','unknown')", ()),
            ("INSERT OR REPLACE INTO capture_failure_boundaries VALUES(1,3,'timeout','unknown')", ()),
            ("UPDATE capture_clocks SET monotonic_us=0 WHERE frame_id='5'", ()),
            ("UPDATE consumption_records SET result=? WHERE segment_id='a' AND event_id=9",
             ('{"observation_accepted":true,"state":"ambiguous"}',)),
            ("DELETE FROM consumption_records WHERE segment_id='a' AND event_id=2", ()),
            ("DELETE FROM capture_failure_boundaries WHERE failure_id=1", ()),
        ]
        for sql, args in mutations:
            with self.subTest(sql=sql):
                with self.store.connect() as db:
                    db.execute(sql, args)
                self.assert_same_gaps()

    def test_protected_shared_digest_refreshes_after_training_and_review_changes(self):
        _, candidates = self.worker.candidates()
        image = candidates[0]
        with self.store.connect() as db:
            db.execute('UPDATE frames SET training_allowed=1 WHERE sha256=?', (image,))
        self.assertNotIn(image, self.worker.candidates()[1])
        with self.store.connect() as db:
            db.execute('UPDATE frames SET training_allowed=0 WHERE sha256=?', (image,))
            db.execute("INSERT INTO human_reviews VALUES(1,?,'context','review','{}')", (image,))
        self.assertNotIn(image, self.worker.candidates()[1])
        with self.store.connect() as db:
            db.execute("INSERT OR REPLACE INTO human_reviews VALUES(2,?,'context','review','{}')", (candidates[1],))
        refreshed = self.worker.candidates()[1]
        self.assertIn(image, refreshed)
        self.assertNotIn(candidates[1], refreshed)
        _, original = self.blobs[image]
        self.store.add('fixture', original, headers('duplicate', original))
        self.assertNotIn(image, self.worker.candidates()[1])

    def test_new_failure_between_plan_and_intent_preserves_photo(self):
        cutoff, candidates = self.worker.candidates()
        image = candidates[0]
        event, _ = self.blobs[image]
        original_plan = self.worker._plan
        def new_boundary(*args, **kwargs):
            plan = original_plan(*args, **kwargs)
            with self.store.connect() as db:
                db.execute("INSERT INTO capture_failure_boundaries VALUES(1,?,'timeout','unknown')", (event,))
            return plan
        with patch.object(self.worker, '_plan', side_effect=new_boundary):
            self.worker.retire([image], cutoff)
        self.assertNotIn(image, self.worker.candidates()[1])
        with self.store.connect() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM retired_images WHERE sha256=?', (image,)).fetchone())

    def test_archive_enabled_after_final_plan_prevents_unlink(self):
        cutoff, candidates = self.worker.candidates()
        image = candidates[0]
        self.worker.retire([image], cutoff)
        original_plan = self.worker._plan
        def enable_archive(*args, **kwargs):
            plan = original_plan(*args, **kwargs)
            self.archive.save(dict(enabled=True, directory='/media/new'), self.archive.status()['revision'])
            return plan
        with patch.object(self.worker, '_plan', side_effect=enable_archive):
            self.assertEqual(self.worker.finish_pending(), 0)
        self.worker.finish_pending()
        self.assertEqual(self.store.image(image), self.blobs[image][1])
        with self.store.connect() as db:
            self.assertIsNone(db.execute('SELECT 1 FROM retired_images WHERE sha256=?', (image,)).fetchone())

    def test_reference_added_after_final_plan_prevents_unlink(self):
        cutoff, candidates = self.worker.candidates()
        image = candidates[0]
        self.worker.retire([image], cutoff)
        original_plan = self.worker._plan
        def add_reference(*args, **kwargs):
            plan = original_plan(*args, **kwargs)
            references = self.root / 'references'
            references.mkdir(exist_ok=True)
            (references / (image+'.image')).touch()
            return plan
        with patch.object(self.worker, '_plan', side_effect=add_reference):
            self.worker.finish_pending()
        self.worker.finish_pending()
        self.assertEqual(self.store.image(image), self.blobs[image][1])
