"""Offline package checks using synthetic firmware, models and images."""
import hashlib,json,struct,subprocess,sys,tempfile,unittest,zipfile
from pathlib import Path
from device_bundle_manifest import digest,make_device_manifest
HERE=Path(__file__).resolve().parent

def image():
 h=bytearray(24);h[0]=0xe9;h[1]=1;h[23]=1
 data=b'synthetic';raw=bytes(h)+struct.pack('<II',0x3ffb0000,len(data))+data
 checksum=0xef
 for b in data:checksum^=b
 raw+=bytes((16-(len(raw)+1)%16)%16)+bytes([checksum])
 return raw+hashlib.sha256(raw).digest()

class PackageTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.files={'firmware/firmware.bin':image(),'html/index.html':b'page','model/polar-int8.tflite':b'secondary','model/polar-main-int8.tflite':b'main','diagnostics/polar-runtime-vectors.bin':b'synthetic-vectors','diagnostics/replay-0.jpg':b'synthetic-image'}
  self.files['device-manifest.json']=make_device_manifest(self.files,digest(b'secondary'),'required_bundle')
  self.files['config/private.ini']=b'must-not-copy';self.files['validation/result.json']=b'private';self.files['docs/Licence.md']=b'license'
  self.seed=self.root/'seed.zip'
  with zipfile.ZipFile(self.seed,'w') as z:
   for name,data in self.files.items():z.writestr(name,data)
  self.firmware=self.root/'firmware.bin';self.firmware.write_bytes(image());self.output=self.root/'out.zip'
 def run_package(self,*extra,sha=None):
  return subprocess.run([sys.executable,str(HERE/'package_from_release.py'),'--seed',str(self.seed),'--seed-sha256',sha or digest(self.seed.read_bytes()),'--firmware',str(self.firmware),'--output',str(self.output),*extra],capture_output=True,text=True)
 def test_without_diagnostics(self):
  result=self.run_package('--without-diagnostics');self.assertEqual(result.returncode,0,result.stderr)
  with zipfile.ZipFile(self.output) as z:
   self.assertFalse(any(n.startswith(('diagnostics/','config/','validation/')) for n in z.namelist()))
   m=json.loads(z.read('device-manifest.json'))
   self.assertEqual(set(m['assets']),{'html/index.html','model/polar-int8.tflite','model/polar-main-int8.tflite'})
   for name,metadata in m['assets'].items():
    self.assertEqual(z.read(name),self.files[name]);self.assertEqual(digest(z.read(name)),metadata['sha256'])
   self.assertEqual(z.read('docs/Licence.md'),b'license')
   self.assertNotEqual(m['bundle_id'],json.loads(self.files['device-manifest.json'])['bundle_id'])
  self.assertFalse(json.loads(self.output.with_suffix('.json').read_text())['diagnostics_included'])
 def test_default_preserves_diagnostics(self):
  result=self.run_package();self.assertEqual(result.returncode,0,result.stderr)
  with zipfile.ZipFile(self.output) as z:self.assertEqual(z.read('diagnostics/replay-0.jpg'),b'synthetic-image')
 def test_wrong_seed_has_no_output(self):
  self.assertNotEqual(self.run_package('--without-diagnostics',sha='0'*64).returncode,0);self.assertFalse(self.output.exists())
 def test_refuses_overwrite(self):
  self.output.write_bytes(b'existing');self.assertNotEqual(self.run_package('--without-diagnostics').returncode,0);self.assertEqual(self.output.read_bytes(),b'existing')
 def test_ui_and_model_remain_required(self):
  files=dict(self.files);del files['html/index.html']
  with self.assertRaises(ValueError):make_device_manifest(files,digest(b'secondary'))
  files=dict(self.files)
  with self.assertRaises(ValueError):make_device_manifest(files,'0'*64)

if __name__=='__main__':unittest.main()
