import copy,json,unittest
import test_build_review_gallery as gallery_fixture
from record_review_labels import record
from image_archive_store import digest

class LabelTests(unittest.TestCase):
 def setUp(self):
  fixture=gallery_fixture.GalleryTests();fixture.setUp();self.addCleanup(fixture.doCleanups);fixture.generate()
  self.f=fixture;self.review=fixture.output/'review.json';self.answers=fixture.base/'answers.json';self.output=fixture.base/'labels.json'
  self.submission=dict(version=1,review_sha256=digest(self.review.read_bytes()),reviewer='fixture reviewer',method='independent_reading',dials=['main','secondary'],images=[dict(image_sha256=digest(fixture.image),readings={'main':5.3,'secondary':None})])
 def run_record(self):
  self.answers.write_text(json.dumps(self.submission),encoding='utf-8')
  return record(self.f.root,self.review,self.answers,self.f.protection,self.output)
 def test_record_preserves_inputs_and_unknown_without_training(self):
  before={str(p):p.read_bytes() for p in self.f.root.rglob('*') if p.is_file()};original=self.review.read_bytes()
  r=self.run_record();self.assertFalse(r['training_eligible']);self.assertIsNone(r['images'][0]['readings']['secondary']);self.assertEqual(r['images'][0]['split'],'unassigned');self.assertEqual(r['method'],'independent_reading')
  self.assertEqual(original,self.review.read_bytes());self.assertEqual(before,{str(p):p.read_bytes() for p in self.f.root.rglob('*') if p.is_file()})
 def test_current_protection_checked_not_only_export_time(self):
  self.f.protection.write_text(json.dumps(dict(version=1,image_sha256s=[digest(self.f.image)])))
  with self.assertRaises(ValueError):self.run_record()
  self.assertFalse(self.output.exists())
 def test_invalid_values_and_duplicate_images_fail_before_write(self):
  original=copy.deepcopy(self.submission)
  for value in [True,False,'5.3',-1,10,float('nan'),float('inf'),[],{}]:
   self.submission=copy.deepcopy(original);self.submission['images'][0]['readings']['main']=value
   with self.assertRaises(ValueError):self.run_record()
   self.assertFalse(self.output.exists())
  self.submission=copy.deepcopy(original);self.submission['images']*=2
  with self.assertRaises(ValueError):self.run_record()
 def test_review_hash_and_unknown_image_rejected(self):
  self.submission['review_sha256']='0'*64
  with self.assertRaises(ValueError):self.run_record()
  self.submission['review_sha256']=digest(self.review.read_bytes());self.submission['images'][0]['image_sha256']='f'*64
  with self.assertRaises(ValueError):self.run_record()
 def test_missing_dial_and_undeclared_source_rejected(self):
  del self.submission['images'][0]['readings']['secondary']
  with self.assertRaises(ValueError):self.run_record()
  self.submission['images'][0]['readings']['secondary']=None;self.submission['method']='model_prediction'
  with self.assertRaises(ValueError):self.run_record()
 def test_changed_blob_rejected(self):
  next((self.f.root/'blobs').glob('*.image')).write_bytes(b'changed')
  with self.assertRaises(ValueError):self.run_record()
 def test_no_overwrite_or_archive_or_gallery_output(self):
  self.run_record();data=self.output.read_bytes()
  with self.assertRaises(ValueError):self.run_record()
  self.assertEqual(self.output.read_bytes(),data)
  for directory in [self.f.root,self.f.output]:
   self.output=directory/'labels.json'
   with self.assertRaises(ValueError):self.run_record()
 def test_assisted_confirmation_is_explicit(self):
  self.submission['method']='confirmation_of_shown_estimate'
  self.assertEqual(self.run_record()['method'],'confirmation_of_shown_estimate')
 def bind_form(self,dials):
  review=json.loads(self.review.read_text(encoding='utf-8'));review['label_form_dials']=dials
  self.review.write_text(json.dumps(review),encoding='utf-8')
  self.submission['review_sha256']=digest(self.review.read_bytes())
 def test_form_dials_must_match_names_and_order(self):
  original=copy.deepcopy(self.submission)
  for n,form in enumerate([['secondary','main'],['main','other'],['main'],['main','secondary','other']]):
   with self.subTest(form=form):
    self.output=self.f.base/f'mismatch-{n}.json'
    self.submission=copy.deepcopy(original);self.bind_form(form)
    with self.assertRaisesRegex(ValueError,'dial'):self.run_record()
    self.assertFalse(self.output.exists())
 def test_invalid_declared_form_dials_do_not_fall_back_to_unbound(self):
  for n,form in enumerate([None,[],{},'main',True,['main','main'],['main',3]]):
   with self.subTest(form=form):
    self.output=self.f.base/f'invalid-form-{n}.json'
    self.bind_form(form)
    with self.assertRaisesRegex(ValueError,'dial'):self.run_record()
    self.assertFalse(self.output.exists())
 def test_matching_form_dials_record_provenance(self):
  self.bind_form(['main','secondary'])
  r=self.run_record()
  self.assertEqual(r['dial_name_source'],'gallery_form')
  self.assertEqual(r['dials'],['main','secondary'])
  self.assertIsNone(r['images'][0]['readings']['secondary'])
 def test_view_only_gallery_keeps_explicit_user_dial_declaration(self):
  r=self.run_record()
  self.assertEqual(r['dial_name_source'],'reviewer_declaration')
if __name__=='__main__':unittest.main()
