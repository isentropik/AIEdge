import json
from pathlib import Path
import tempfile
import unittest
from image_archive_store import digest,store_settings,store_capture
from prepare_training_review import prepare

class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'archive';self.protection=Path(self.tmp.name)/'protected.json'
        self.protection.write_text(json.dumps(dict(version=1,image_sha256s=[])))
        self.image=b'synthetic image';self.settings=b'capture-settings-v1\nresolution=640x480\n'
        self.metadata=dict(version=1,device_id='test',boot_id='boot1',capture_us=42,capture_utc=None,
            image_sha256=digest(self.image),image_bytes=len(self.image),firmware_sha256='1'*64,
            model_sha256='2'*64,calibration_sha256='3'*64,settings_sha256=digest(self.settings))
        store_settings(self.root,digest(self.settings),self.settings);self.put()
    def put(self):store_capture(self.root,self.metadata,self.image)
    def run_review(self):return prepare(self.root,self.protection)
    def test_preserves_sources_and_never_labels(self):
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        r=self.run_review();image=r['groups'][0]['images'][0]
        self.assertIsNone(image['label']);self.assertFalse(image['training_eligible'])
        self.assertEqual(image['split'],'unassigned');self.assertIsNone(image['captures'][0]['capture_utc'])
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
    def test_protected_hash_excludes_all_captures(self):
        self.metadata['capture_us']+=1;self.put()
        self.protection.write_text(json.dumps(dict(version=1,image_sha256s=[digest(self.image)])))
        r=self.run_review();self.assertEqual(r['groups'],[])
        self.assertEqual(r['excluded'][0]['reason'],'protected');self.assertEqual(len(r['excluded'][0]['capture_ids']),2)
    def test_exact_duplicates_collapse_but_keep_capture_provenance(self):
        self.metadata['capture_us']+=1;self.put();r=self.run_review()
        self.assertEqual(len(r['groups'][0]['images']),1);self.assertEqual(len(r['groups'][0]['images'][0]['captures']),2)
    def test_conflicting_identity_is_not_arbitrarily_selected(self):
        self.metadata['capture_us']+=1;self.metadata['calibration_sha256']='4'*64;self.put()
        r=self.run_review();self.assertEqual(r['groups'],[])
        self.assertEqual(r['excluded'][0]['reason'],'conflicting_capture_settings')
    def test_different_images_with_changed_settings_remain_separate(self):
        self.image=b'another image';self.metadata.update(capture_us=43,image_sha256=digest(self.image),image_bytes=len(self.image),firmware_sha256='5'*64);self.put()
        self.assertEqual(len(self.run_review()['groups']),2)
    def test_corruption_refuses_entire_review(self):
        next((self.root/'blobs').iterdir()).write_bytes(b'corrupt')
        with self.assertRaises(ValueError):self.run_review()
    def test_missing_or_invalid_protection_is_not_empty_protection(self):
        for value in [dict(version=True,image_sha256s=[]),dict(version=1,image_sha256s=['bad']),{},dict(version=1,image_sha256s='')]:
            self.protection.write_text(json.dumps(value))
            with self.assertRaises(ValueError):self.run_review()
        self.protection.unlink()
        with self.assertRaises(ValueError):self.run_review()

    def test_cli_refuses_overwrite_and_archive_output(self):
        import subprocess,sys
        from prepare_training_review import __file__ as script
        for output in [Path(self.tmp.name)/'existing.json',self.root/'review.json']:
            if output.name=='existing.json':output.write_bytes(b'keep my review')
            result=subprocess.run([sys.executable,script,str(self.root),'--protected-hashes',str(self.protection),'--output',str(output)],capture_output=True)
            self.assertEqual(result.returncode,2)
            if output.name=='existing.json':self.assertEqual(output.read_bytes(),b'keep my review')
            else:self.assertFalse(output.exists())
    def test_cli_creates_separate_unconfirmed_review(self):
        import subprocess,sys
        from prepare_training_review import __file__ as script
        output=Path(self.tmp.name)/'review.json'
        result=subprocess.run([sys.executable,script,str(self.root),'--protected-hashes',str(self.protection),'--output',str(output)],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(json.loads(output.read_text())['training_eligible'])

if __name__=='__main__':unittest.main()
