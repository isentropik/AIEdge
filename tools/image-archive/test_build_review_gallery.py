import io,json,tempfile,unittest
from pathlib import Path
from PIL import Image
from build_review_gallery import build
from prepare_training_review import prepare
from image_archive_store import digest,store_settings,store_capture

class GalleryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.base=Path(self.tmp.name);self.root=self.base/'archive';self.output=self.base/'gallery';self.protection=self.base/'protection.json'
  self.protection.write_text(json.dumps(dict(version=1,image_sha256s=[])))
  self.settings=b'capture-settings-v1\nfixture=1\n';store_settings(self.root,digest(self.settings),self.settings)
  buffer=io.BytesIO();Image.new('RGB',(64,48),(100,120,140)).save(buffer,format='JPEG');self.image=buffer.getvalue()
  self.meta=dict(version=1,device_id='fixture',boot_id='test',capture_us=5,capture_utc=None,image_sha256=digest(self.image),image_bytes=len(self.image),firmware_sha256='1'*64,model_sha256='2'*64,calibration_sha256='3'*64,settings_sha256=digest(self.settings))
  store_capture(self.root,self.meta,self.image);self.group=prepare(self.root,self.protection)['groups'][0]['group_id']
 def generate(self,**kwargs):return build(self.root,self.protection,self.group,self.output,**kwargs)
 def test_original_bytes_metadata_and_archive_preserved(self):
  original={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
  r=self.generate();self.assertFalse(r['training_eligible']);self.assertIsNone(r['images'][0]['label'])
  self.assertEqual(next(self.output.glob('*.jpg')).read_bytes(),self.image)
  page=(self.output/'index.html').read_text(encoding='utf-8')
  self.assertIn('UTC unknown',page);self.assertIn('width=device-width',page);self.assertIn('value="dark"',page)
  self.assertEqual(original,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
 def test_existing_review_never_overwritten(self):
  self.generate();(self.output/'index.html').write_text('keep')
  with self.assertRaises(ValueError):self.generate()
  self.assertEqual((self.output/'index.html').read_text(),'keep')
 def test_protection_applied_again_at_export(self):
  self.protection.write_text(json.dumps(dict(version=1,image_sha256s=[digest(self.image)])))
  with self.assertRaises(ValueError):self.generate()
  self.assertFalse(self.output.exists())
 def test_invalid_bounds_and_archive_destination(self):
  for kwargs in [dict(limit=13),dict(limit=0),dict(offset=-1),dict(offset=1)]:
   with self.assertRaises(ValueError):self.generate(**kwargs)
  with self.assertRaises(ValueError):build(self.root,self.protection,self.group,self.root/'gallery')
 def test_hashed_but_undecodable_image_rejected_before_output(self):
  # Receiver stores opaque bytes; a good hash alone is not an image decoder check.
  data=b'not a JPEG';meta=dict(self.meta,capture_us=6,image_sha256=digest(data),image_bytes=len(data))
  store_capture(self.root,meta,data)
  with self.assertRaises(OSError):self.generate()
  self.assertFalse(self.output.exists())
 def test_png_original_bytes_preserved(self):
  stream=io.BytesIO();Image.new('RGB',(8,8)).save(stream,format='PNG');data=stream.getvalue()
  meta=dict(self.meta,capture_us=6,image_sha256=digest(data),image_bytes=len(data));store_capture(self.root,meta,data)
  self.generate();self.assertEqual(next(self.output.glob('*.png')).read_bytes(),data)

if __name__=='__main__':unittest.main()
