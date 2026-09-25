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

    def test_readback_waits_for_concurrent_publication(self):
        import threading
        import image_archive_store as store
        path=self.root/'object';data=b'complete immutable object'
        publishing=threading.Event();release=threading.Event();reader_ready=threading.Event();opened=threading.Event()
        operation='rename' if store.os.name=='nt' else 'link'
        native=getattr(store.os,operation);open_real=Path.open
        def delayed_publish(source,destination):
            publishing.set()
            if not release.wait(5): raise TimeoutError('test publication was not released')
            return native(source,destination)
        def observe_open(candidate,*args,**kwargs):
            if candidate==path and args==('rb',):opened.set()
            return open_real(candidate,*args,**kwargs)
        def readback():
            reader_ready.set()
            return store.matches_existing(path,data)
        with patch.object(store.os,operation,delayed_publish),patch.object(Path,'open',observe_open),ThreadPoolExecutor(max_workers=2) as pool:
            writer=pool.submit(store.write_immutable,path,data)
            try:
                self.assertTrue(publishing.wait(5))
                reader=pool.submit(readback);self.assertTrue(reader_ready.wait(5))
                self.assertFalse(opened.wait(.05),'reader entered during publication')
            finally:release.set()
            self.assertTrue(writer.result(timeout=5));self.assertTrue(reader.result(timeout=5))
        self.assertEqual(path.read_bytes(),data)

    def test_permission_failure_is_not_acknowledged_or_retried(self):
        self.put()
        with patch.object(Path,'open',side_effect=PermissionError('storage denied')) as opened:
            with self.assertRaises(PermissionError):self.put()
        self.assertEqual(opened.call_count,1)

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

    def test_oversized_retry_objects_are_read_with_a_bound(self):
        from image_archive_store import store_settings
        descriptor=b'capture-settings-v1\nfixture=1\n'
        for kind in ('blob','record','settings'):
            with self.subTest(kind=kind):
                self.put()
                settings_hash=digest(descriptor)
                store_settings(self.root,settings_hash,descriptor)
                path=(next((self.root/'blobs').glob('*.image')) if kind=='blob' else
                      next((self.root/'captures').glob('*.json')) if kind=='record' else
                      self.root/'settings'/f'{settings_hash}.txt')
                original=path.read_bytes();path.write_bytes(original+b'x'*65536)
                open_real=Path.open;reads=[]
                class Reader:
                    def __init__(self,stream):self.stream=stream
                    def __enter__(self):return self
                    def __exit__(self,*args):self.stream.close()
                    def read(self,size=-1):
                        if size<0 or size>len(original)+1:raise AssertionError('Unbounded archive read')
                        reads.append(size);return self.stream.read(size)
                def bounded_open(candidate,*args,**kwargs):
                    stream=open_real(candidate,*args,**kwargs)
                    return Reader(stream) if candidate==path and args==('rb',) else stream
                try:
                    with patch.object(Path,'open',bounded_open),self.assertRaises(ArchiveConflict):
                        store_settings(self.root,settings_hash,descriptor) if kind=='settings' else self.put()
                    self.assertTrue(reads)
                    self.assertEqual(path.stat().st_size,len(original)+65536)
                finally:path.write_bytes(original)

    def test_failed_publish_has_no_receipt_or_partial_final(self):
        with patch('image_archive_store.publish_no_replace', side_effect=OSError('storage unavailable')):
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
