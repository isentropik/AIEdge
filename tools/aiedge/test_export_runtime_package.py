"""Offline export regression tests; all assets are synthetic."""
import json,tempfile,unittest,zipfile
from pathlib import Path
from test_package_from_release import image
from device_bundle_manifest import digest,make_device_manifest
from export_runtime_package import export_package

class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.seed=self.root/'seed.zip';self.out=self.root/'out.zip'
        self.files={'firmware/firmware.bin':image(),'html/index.html':b'page',
            'model/polar-int8.tflite':b'model','docs/Licence.md':b'credit',
            'manifest.json':b'private paths','validation/private.jpg':b'private image'}
        self.seal()
    def seal(self):
        self.files['device-manifest.json']=make_device_manifest(self.files,digest(b'model'),'required_bundle')
        self.write()
    def write(self):
        with zipfile.ZipFile(self.seed,'w') as z:
            for n,d in self.files.items():z.writestr(n,d)
    def export(self):return export_package(self.seed,digest(self.seed.read_bytes()),self.out)
    def test_preserves_identity_and_omits_private_extras(self):
        result=self.export()
        self.assertTrue(result['runtime_unchanged'])
        with zipfile.ZipFile(self.out) as z:
            self.assertEqual(set(z.namelist()),{'firmware/firmware.bin','html/index.html','model/polar-int8.tflite','docs/Licence.md','device-manifest.json'})
            for n in z.namelist():self.assertEqual(z.read(n),self.files[n])
            self.assertEqual(json.loads(z.read('device-manifest.json'))['bundle_id'],result['bundle_id'])
    def test_rejects_changed_runtime(self):
        self.files['html/index.html']=b'changed';self.write()
        with self.assertRaisesRegex(ValueError,'verification failed'):self.export()
        self.assertFalse(self.out.exists())
    def test_rejects_diagnostic_asset(self):
        self.files['diagnostics/private.jpg']=b'private';self.seal()
        with self.assertRaisesRegex(ValueError,'refuses diagnostic'):self.export()
        self.assertFalse(self.out.exists())
    def test_rejects_path_traversal(self):
        self.files['html/../private']=b'private';self.seal()
        with self.assertRaises(ValueError):self.export()
        self.assertFalse(self.out.exists())
    def test_rejects_duplicate_entries(self):
        with zipfile.ZipFile(self.seed,'a') as z:z.writestr('html/index.html',b'other')
        with self.assertRaisesRegex(ValueError,'Duplicate'):self.export()
        self.assertFalse(self.out.exists())
    def test_wrong_seed_hash(self):
        with self.assertRaisesRegex(ValueError,'hash mismatch'):export_package(self.seed,'0'*64,self.out)
        self.assertFalse(self.out.exists())
    def test_refuses_overwrite(self):
        self.out.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError,'already exists'):self.export()
        self.assertEqual(self.out.read_bytes(),b'keep')
    def test_rejects_changed_firmware(self):
        self.files['firmware/firmware.bin']=image(b'different');self.write()
        with self.assertRaisesRegex(ValueError,'verification failed'):self.export()
        self.assertFalse(self.out.exists())

if __name__=='__main__':unittest.main()
