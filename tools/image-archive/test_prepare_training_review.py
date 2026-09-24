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

    def add_image(self,seconds,boot='boot1',device='test',data=None):
        image=data or str((seconds,boot,device)).encode()
        m=dict(self.metadata,capture_us=seconds*1000000+42,boot_id=boot,device_id=device,image_sha256=digest(image),image_bytes=len(image))
        store_capture(self.root,m,image)
        return digest(image)
    def protect_first(self):
        self.protection.write_text(json.dumps(dict(version=1,image_sha256s=[digest(self.image)])))
    def test_time_window_inclusive_and_does_not_chain(self):
        near=self.add_image(300);far=self.add_image(301);self.protect_first()
        r=self.run_review();excluded={x['image_sha256']:x for x in r['excluded']}
        self.assertEqual(excluded[near]['reason'],'protected_time_neighbor')
        self.assertEqual(excluded[near]['temporal_match']['distance_us'],300000000)
        self.assertNotIn(far,excluded);self.assertEqual(r['protect_window_seconds'],300)
    def test_window_works_before_and_after_protected_capture(self):
        first=digest(self.image);middle=self.add_image(400);last=self.add_image(699)
        self.protection.write_text(json.dumps(dict(version=1,image_sha256s=[middle])))
        r=prepare(self.root,self.protection,400)
        excluded={x['image_sha256']:x['reason'] for x in r['excluded']}
        self.assertEqual(excluded[first],'protected_time_neighbor');self.assertEqual(excluded[last],'protected_time_neighbor')
    def test_monotonic_clock_never_compared_across_boots_or_devices(self):
        boot=self.add_image(1,boot='boot2');device=self.add_image(1,device='other');self.protect_first()
        excluded={x['image_sha256'] for x in self.run_review()['excluded']}
        self.assertNotIn(boot,excluded);self.assertNotIn(device,excluded)
    def test_hash_is_excluded_if_any_occurrence_is_near_protected(self):
        other=b'same image twice';h=self.add_image(1,data=other);self.add_image(900,data=other);self.protect_first()
        row=next(x for x in self.run_review()['excluded'] if x['image_sha256']==h)
        self.assertEqual(len(row['capture_ids']),2);self.assertEqual(row['reason'],'protected_time_neighbor')
    def test_external_hash_without_timestamps_is_reported(self):
        self.protection.write_text(json.dumps(dict(version=1,image_sha256s=['f'*64])))
        self.assertEqual(self.run_review()['protected_hashes_without_capture_records'],['f'*64])
    def test_explicit_disable_and_invalid_windows(self):
        near=self.add_image(1);self.protect_first()
        self.assertNotIn(near,{x['image_sha256'] for x in prepare(self.root,self.protection,0)['excluded']})
        for value in [-1,86401,True,1.5]:
            with self.assertRaises(ValueError):prepare(self.root,self.protection,value)

if __name__=='__main__':unittest.main()
