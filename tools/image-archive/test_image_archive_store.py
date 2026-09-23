"""Receiver storage tests on disposable local files only."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from image_archive_store import ArchiveConflict, digest, store_capture


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.image = b'opaque original image bytes'
        self.metadata = dict(version=1, device_id='meter', boot_id='abc', capture_us=1234,
            capture_utc=None, image_sha256=digest(self.image), image_bytes=len(self.image),
            firmware_sha256='1'*64, model_sha256='2'*64, calibration_sha256='3'*64, settings_sha256='4'*64)

    def put(self, metadata=None):
        return store_capture(self.root, self.metadata if metadata is None else metadata, self.image)

    def test_retry_and_distinct_capture(self):
        first = self.put()
        self.assertFalse(first['duplicate'])
        self.assertTrue(self.put()['duplicate'])
        self.metadata['capture_us'] += 1
        self.assertNotEqual(first['capture_id'], self.put()['capture_id'])
        self.assertEqual(len(list((self.root/'blobs').glob('*.image'))), 1)
        record = json.loads(next((self.root/'captures').glob('*.json')).read_text())
        self.assertIsNone(record['metadata']['capture_utc'])
        self.assertFalse(record['training_eligible'])

    def test_concurrent_retries(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            receipts = list(pool.map(lambda _: self.put(), range(24)))
        self.assertEqual(sum(not r['duplicate'] for r in receipts), 1)

    def test_conflict_preserves_record(self):
        self.put()
        before = next((self.root/'captures').glob('*.json')).read_bytes()
        self.metadata['model_sha256'] = '5'*64
        with self.assertRaises(ArchiveConflict): self.put()
        self.assertEqual(next((self.root/'captures').glob('*.json')).read_bytes(), before)

    def test_corrupt_blob_is_not_acknowledged(self):
        self.put()
        next((self.root/'blobs').glob('*.image')).write_bytes(b'corrupt')
        with self.assertRaises(ArchiveConflict): self.put()

    def test_failed_publish_has_no_receipt_or_partial_final(self):
        with patch('image_archive_store.os.link', side_effect=OSError('storage unavailable')):
            with self.assertRaises(OSError): self.put()
        self.assertFalse(list(self.root.rglob('*.image')))
        self.assertFalse(list(self.root.rglob('.pending-*')))
        self.assertFalse(self.put()['duplicate'])

    def test_directory_sync_failure_is_not_acknowledged(self):
        # Existing directories isolate object publication from directory creation.
        (self.root/'blobs').mkdir();(self.root/'captures').mkdir()
        def fail_after_blob_publish(path):
            if list((self.root/'blobs').glob('*.image')):
                raise OSError('sync failed after link publication')
        with patch('image_archive_store.sync_directory',side_effect=fail_after_blob_publish):
            with self.assertRaises(OSError):self.put()
        self.assertEqual(len(list((self.root/'blobs').glob('*.image'))),1)
        self.assertFalse(list((self.root/'captures').glob('*.json')))
        with patch('image_archive_store.sync_directory') as sync:
            receipt=self.put()
            self.assertFalse(receipt['duplicate'])
            self.assertIn(((self.root/'blobs',),),[(c.args,) for c in sync.call_args_list])
        with patch('image_archive_store.sync_directory',side_effect=OSError('retry sync failed')):
            with self.assertRaises(OSError):self.put()

    def test_nested_directory_creation_is_synced(self):
        self.root=self.root/'nested'/'archive'
        with patch('image_archive_store.sync_directory') as sync:
            self.put()
        paths=[c.args[0] for c in sync.call_args_list]
        self.assertIn(self.root.parent,paths)
        self.assertIn(self.root,paths)
        self.assertIn(self.root/'blobs',paths)
        self.assertIn(self.root/'captures',paths)

    def test_invalid_metadata_and_hash(self):
        for key, value in [('device_id','../escape'),('boot_id','a/b'),('capture_us',True),
                           ('capture_us',-1),('capture_utc','2026-09-22T12:00:00'),
                           ('image_sha256','0'*64),('image_bytes',999),('review_status','confirmed')]:
            metadata = copy.deepcopy(self.metadata); metadata[key] = value
            with self.subTest(key=key,value=value), self.assertRaises(ValueError): self.put(metadata)
        self.assertFalse(list(self.root.rglob('*.image')))


if __name__ == '__main__':
    unittest.main()
