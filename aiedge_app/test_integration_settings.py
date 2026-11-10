import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from retention_settings import read, save, DEFAULTS
from published_usage import snapshot
from test_image_retention import ImageRetentionTests as Fixture
from image_retention import ImageRetention


class SettingsTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)

    def test_persist_restart_conflict_and_no_other_files(self):
        self.assertEqual(read(self.root)['config'],DEFAULTS)
        value=dict(recent_events=10,older_images=0,older_megabytes=0)
        result=save(self.root,value,'default')
        self.assertEqual(read(self.root),result)
        self.assertEqual(result['config'],value)
        with self.assertRaises(ValueError):save(self.root,DEFAULTS,'default')
        self.assertEqual(read(self.root),result)
        self.assertEqual([p.name for p in self.root.iterdir()],['image-retention.json'])

    def test_invalid_values_never_save(self):
        for value in (True, -1, 2001, 1.5, '500',None):
            with self.subTest(value=value),self.assertRaises(ValueError):
                save(self.root,dict(DEFAULTS,recent_events=value),'default')
        with self.assertRaises(ValueError):save(self.root,dict(DEFAULTS,unknown=1),'default')
        self.assertEqual(read(self.root)['revision'],'default')

    def test_corrupt_duplicate_and_oversize_fail_closed(self):
        for body in ('{', '{"recent_events":1,"recent_events":2,"older_images":0,"older_megabytes":0}', ' '*4097):
            (self.root/'image-retention.json').write_text(body)
            with self.assertRaises(ValueError):read(self.root)


class ProtectionTests(unittest.TestCase):
    def setUp(self):Fixture.setUp(self)

    def test_zero_ordinary_budget_keeps_all_gap_sides_and_ledger(self):
        with self.store.connect() as db:
            for event in (2,6,8):db.execute("INSERT INTO capture_failure_boundaries VALUES(?,?,'camera_timeout','unknown')",(event,event))
            before=db.execute('SELECT * FROM capture_failure_boundaries').fetchall()
        self.worker.save_settings(dict(recent_events=1,older_images=0,older_megabytes=0),'default')
        self.worker.sweep()
        images=list(self.blobs)
        for index in (1,2,5,6,7,8):self.assertTrue((self.root/'images'/(images[index]+'.jpg')).exists())
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT * FROM capture_failure_boundaries').fetchall(),before)
            self.assertEqual(db.execute('SELECT count(*) FROM capture_events').fetchone()[0],12)
        self.assertEqual(self.store.retention_evidence['budget_excluded_pairs'],0)
        self.assertEqual(self.store.retention_evidence['selected_older_images'],0)

    def test_settings_increase_cancels_pending_deletion(self):
        cutoff,images=self.worker.candidates();image=images[0]
        self.worker.retire([image],cutoff)
        self.worker.save_settings(dict(recent_events=2000,older_images=0,older_megabytes=0),'default')
        restarted=ImageRetention(self.store,self.archive)
        restarted.finish_pending()
        self.assertTrue((self.root/'images'/(image+'.jpg')).exists())
        with self.store.connect() as db:self.assertIsNone(db.execute('SELECT * FROM retired_images WHERE sha256=?',(image,)).fetchone())

    def test_corrupt_settings_prevent_deletion(self):
        cutoff,images=self.worker.candidates();self.worker.retire(images,cutoff)
        (self.root/'image-retention.json').write_text('{')
        with self.assertRaises(ValueError):self.worker.finish_pending()
        for image in images:self.assertTrue((self.root/'images'/(image+'.jpg')).exists())

    def test_surviving_half_is_kept_when_other_side_missing(self):
        images=list(self.blobs)
        with self.store.connect() as db:db.execute("INSERT INTO capture_failure_boundaries VALUES(7,7,'camera_timeout','unknown')")
        (self.root/'images'/(images[6]+'.jpg')).unlink()
        self.worker.save_settings(dict(recent_events=1,older_images=0,older_megabytes=0),'default')
        self.worker.sweep()
        self.assertTrue((self.root/'images'/(images[7]+'.jpg')).exists())
        self.assertGreater(self.store.retention_evidence['missing_endpoint_pairs'],0)


class PublishedTests(unittest.TestCase):
    def setUp(self):
        self.wall=datetime(2026,11,9,12,tzinfo=timezone.utc)
        self.payload=dict(timezone='UTC',day='2026-11-09',through=dict(event_id=123,captured_at=self.wall.isoformat()),label='10–15 ft³')
        self.publisher=SimpleNamespace(last_good=(self.payload,100,{}),recent=SimpleNamespace(last_good=(self.payload,100,{},'segment')))
        p=patch.dict('os.environ',TZ='UTC');p.start();self.addCleanup(p.stop)

    def test_identity_and_time_unchanged_and_copy(self):
        result=snapshot(self.publisher,now=101,wall=self.wall)
        self.assertEqual(result['daily'],self.payload)
        result['daily']['through']['event_id']=456
        self.assertEqual(self.payload['through']['event_id'],123)

    def test_expiry_future_clock_and_zone(self):
        for now,wall in ((760,self.wall),(99,self.wall),(101,self.wall+timedelta(seconds=660)),(101,self.wall-timedelta(seconds=1))):
            self.assertEqual(snapshot(self.publisher,now=now,wall=wall),{})
        with patch.dict('os.environ',TZ='America/Los_Angeles'):
            self.assertEqual(snapshot(self.publisher,now=101,wall=self.wall),{})

    def test_previous_day_daily_unavailable(self):
        self.payload['day']='2026-11-08'
        result=snapshot(self.publisher,now=101,wall=self.wall)
        self.assertNotIn('daily',result);self.assertIn('recent',result)

    def test_invalidated_publication_unavailable(self):
        self.publisher.last_good=None;self.publisher.recent.last_good=None
        self.assertEqual(snapshot(self.publisher,now=101,wall=self.wall),{})

    def test_malformed_cache_never_breaks_status(self):
        from unittest.mock import Mock
        for value in (Mock(), (), ({},), ('not a payload',100), ({},'bad clock')):
            self.publisher.last_good=value;self.publisher.recent.last_good=value
            self.assertEqual(snapshot(self.publisher,now=101,wall=self.wall),{})


if __name__=='__main__':unittest.main()
