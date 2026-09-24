import io,json,tempfile,unittest
from pathlib import Path
from PIL import Image
from build_review_gallery import build,image_warnings
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
  self.assertIn('UTC unknown \u2014 boot test, capture 5 \u00b5s',page)
  self.assertIn('Unreviewed \u00b7 excluded from training',page)
  self.assertIn('Showing 1\u20131 of 1 unique images',page)
  for damaged in ('\u00c2','\u00e2\u20ac','\ufffd'):self.assertNotIn(damaged,page)
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

 def test_time_neighbor_is_removed_when_exporting(self):
  stream=io.BytesIO();Image.new('RGB',(8,8),(30,20,10)).save(stream,format='PNG');data=stream.getvalue()
  meta=dict(self.meta,capture_us=1000005,image_sha256=digest(data),image_bytes=len(data));store_capture(self.root,meta,data)
  self.protection.write_text(json.dumps(dict(version=1,image_sha256s=[digest(self.image)])))
  with self.assertRaises(ValueError):self.generate()
  self.assertFalse(self.output.exists())
 def test_missing_temporal_anchors_visible_in_gallery(self):
  self.protection.write_text(json.dumps(dict(version=1,image_sha256s=['f'*64])))
  self.generate();page=(self.output/'index.html').read_text(encoding='utf-8')
  self.assertIn('1 protected image hashes have no capture records here',page)
  self.assertIn('300 seconds within the same device boot',page)

class QualityTests(unittest.TestCase):
 def test_exact_blank_colors_and_transparency(self):
  for color in [(0,0,0),(255,255,255),(24,90,130)]:
   with self.subTest(color=color):self.assertIn('Uniform',image_warnings(Image.new('RGB',(8,8),color))[0])
  hidden=Image.new('RGBA',(8,8),(100,20,30,0));hidden.putpixel((0,0),(255,0,0,0))
  self.assertIn('transparent',image_warnings(hidden)[0])
 def test_low_contrast_detail_is_not_rejected(self):
  image=Image.new('RGB',(8,8),(0,0,0));image.putpixel((0,0),(1,0,0))
  self.assertEqual(image_warnings(image),[])
 def test_palette_alpha_detail_is_visible(self):
  image=Image.new('P',(8,8));image.putpalette([0,0,0]*256)
  image.info['transparency']=0;image.putpixel((0,0),1)
  self.assertEqual(image_warnings(image),[])
 def test_warning_export_keeps_review_rows_compatible(self):
  fixture=GalleryTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
  before=prepare(fixture.root,fixture.protection)['groups'][0]['images']
  result=fixture.generate()
  self.assertEqual(result['images'],before)
  self.assertIn('Uniform',result['quality_warnings'][digest(fixture.image)][0])
  self.assertIn('Image warning:',(fixture.output/'index.html').read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
