"""Integrity checks use disposable synthetic receiver records only."""
import json
from pathlib import Path
import tempfile
import unittest
from audit_image_archive import audit
from image_archive_store import canonical, digest, store_capture, store_settings

class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.image = b'synthetic image bytes'
        self.settings = b'capture-settings-v1\nresolution=640x480\n'
        self.metadata = dict(version=1, device_id='test', boot_id='boot1', capture_us=42,
            capture_utc=None, image_sha256=digest(self.image), image_bytes=len(self.image),
            firmware_sha256='1'*64, model_sha256='2'*64, calibration_sha256='3'*64,
            settings_sha256=digest(self.settings))
        store_settings(self.root, self.metadata['settings_sha256'], self.settings)
        self.put()

    def put(self):
        receipt = store_capture(self.root, self.metadata, self.image)
        return self.root/'captures'/(receipt['capture_id']+'.json')

    def test_good_read_only(self):
        before = {str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        r = audit(self.root)
        self.assertEqual((r['valid_records'],r['unique_image_hashes'],r['valid_records_without_utc']), (1,1,1))
        self.assertFalse(r['training_eligible'])
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_repeated_images_and_changed_settings(self):
        self.metadata['capture_us'] += 1
        self.metadata['boot_id'] = 'boot2'
        self.metadata['settings_sha256'] = digest(self.settings+b'light=1\n')
        store_settings(self.root,self.metadata['settings_sha256'],self.settings+b'light=1\n')
        self.put()
        r = audit(self.root)
        self.assertEqual((r['valid_records'],r['repeated_image_records'],len(r['capture_groups'])),(2,1,2))

    def test_corrupt_image(self):
        next((self.root/'blobs').iterdir()).write_bytes(b'bad')
        self.assertEqual(audit(self.root)['invalid_records'],1)

    def test_missing_settings(self):
        next((self.root/'settings').iterdir()).unlink()
        self.assertEqual(audit(self.root)['invalid_records'],1)

    def test_corrupt_settings(self):
        next((self.root/'settings').iterdir()).write_bytes(b'capture-settings-v1\nchanged\n')
        self.assertEqual(audit(self.root)['invalid_records'],1)

    def test_false_training_flag(self):
        p=self.put();r=json.loads(p.read_bytes());r['training_eligible']=True;p.write_bytes(canonical(r))
        self.assertEqual(audit(self.root)['invalid_records'],1)

    def test_duplicate_json_key(self):
        p=self.put();raw=p.read_bytes();p.write_bytes(b'{"capture_id":"bad",'+raw[1:])
        self.assertEqual(audit(self.root)['invalid_records'],1)

    def test_wrong_capture_identity(self):
        p=self.put();p.rename(p.with_name('f'*64+'.json'))
        self.assertEqual(audit(self.root)['invalid_records'],1)

    def test_oversized_record(self):
        self.put().write_bytes(b'x'*16385)
        self.assertEqual(audit(self.root)['invalid_records'],1)

    def test_missing_root(self):
        with self.assertRaises(ValueError):audit(self.root/'absent')

if __name__=='__main__':unittest.main()
