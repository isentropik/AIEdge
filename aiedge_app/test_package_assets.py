import hashlib,json,shutil,tempfile,unittest
from pathlib import Path
from package_assets import verify

class AssetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'assets'
        shutil.copytree(Path(__file__).parent/'assets',self.root)
    def tearDown(self):self.temp.cleanup()
    def test_complete_package(self):
        result=verify(self.root)
        self.assertIn('include/PolarPipeline.h',result['files'])
        self.assertIn('models/polar-main-int8.tflite',result['files'])
        self.assertIn('Licence.md',result['files'])
    def test_modified_asset_rejected(self):
        (self.root/'models/polar-int8.tflite').write_bytes(b'wrong')
        with self.assertRaisesRegex(ValueError,'asset_hash_mismatch'):verify(self.root)
    def test_missing_and_extra_rejected(self):
        p=self.root/'unexpected';p.write_bytes(b'x')
        with self.assertRaisesRegex(ValueError,'unexpected_asset_files'):verify(self.root)
        p.unlink();(self.root/'include/PolarPipeline.h').unlink()
        with self.assertRaisesRegex(ValueError,'asset_hash_mismatch'):verify(self.root)
    def test_manifest_cannot_read_outside_package(self):
        outside=self.root.parent/'outside';outside.write_bytes(b'x')
        manifest={'version':1,'files':{'../outside':hashlib.sha256(b'x').hexdigest()}}
        (self.root/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'invalid_asset_path'):verify(self.root)
