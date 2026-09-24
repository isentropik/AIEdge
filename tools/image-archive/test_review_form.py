import json,shutil,subprocess,unittest
from pathlib import Path
import review_form
import test_build_review_gallery as gallery_fixture
from record_review_labels import record
from image_archive_store import digest

class ReviewFormTests(unittest.TestCase):
 def setUp(self):
  self.f=gallery_fixture.GalleryTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
  self.script=self.f.base/'form.cjs';self.script.write_text(review_form.SCRIPT,encoding='utf-8')
  self.node=shutil.which('node')
  if not self.node:self.fail('Node is required for the mobile label form tests')
 def js(self,code):
  return subprocess.run([self.node,'-e',"const assert=require('node:assert/strict');const form=require("+json.dumps(str(self.script))+");"+code],capture_output=True,text=True,check=True).stdout
 def test_numbers_unknown_and_invalid_values(self):
  self.js("""
  for(const [raw,want] of [['0',0],['9.99',9.99],['.25',.25],[' 5.3 ',5.3],['UNKNOWN',null]])assert.equal(form.reading(raw),want);
  for(const raw of ['', ' ', '10','-1','NaN','Infinity','0x2','2e0','2,5','true'])assert.throws(()=>form.reading(raw));
  """)
 def test_selected_subset_and_missing_answers(self):
  self.js("""
  const cfg={review_sha256:'a'.repeat(64),images:['b'.repeat(64),'c'.repeat(64)],dials:['main']};
  const good={hash:cfg.images[0],include:true,values:{main:'1.25'}};
  const result=form.answers(cfg,' me ','independent_reading',[good,{hash:cfg.images[1],include:false,values:{main:''}}]);
  assert.equal(result.images.length,1);assert.equal(result.reviewer,'me');assert.equal(result.images[0].readings.main,1.25);
  for(const rows of [[],[good,good],[{...good,hash:'bad'}],[{...good,values:{}}],[{...good,values:{main:''}}]])assert.throws(()=>form.answers(cfg,'me','independent_reading',rows));
  for(const [who,method] of [['','independent_reading'],['x'.repeat(101),'independent_reading'],['me',''],['me','model_prediction']])assert.throws(()=>form.answers(cfg,who,method,[good]));
  """)
 def test_export_roundtrip_through_real_label_recorder(self):
  result=self.f.generate(dials=['main','secondary'])
  review=self.f.output/'review.json';raw=review.read_bytes();page=(self.f.output/'index.html').read_text(encoding='utf-8')
  cfg={'review_sha256':digest(raw),'dials':['main','secondary'],'images':[digest(self.f.image)]}
  self.assertIn(json.dumps(cfg),page);self.assertIn('inputmode="decimal"',page)
  code='const cfg='+json.dumps(cfg)+";process.stdout.write(JSON.stringify(form.answers(cfg,'reviewer','independent_reading',[{hash:cfg.images[0],include:true,values:{main:'5.3',secondary:'unknown'}}])));"
  answers=self.f.base/'answers.json';answers.write_text(self.js(code),encoding='utf-8')
  output=self.f.base/'labels.json'
  saved=record(self.f.root,review,answers,self.f.protection,output)
  self.assertEqual(saved['images'][0]['readings'],{'main':5.3,'secondary':None})
  self.assertFalse(saved['training_eligible']);self.assertEqual(review.read_bytes(),raw)
 def test_actual_download_handler_and_error_message(self):
  self.js("""
  const vm=require('node:vm'),fs=require('node:fs');
  const cfg={review_sha256:'a'.repeat(64),images:['b'.repeat(64)],dials:['main']};
  let callback,blob,clicked=false,revoked=false,unknown=false;const message={textContent:''};
  const input={dataset:{dial:'main'},value:'unknown'};
  const field={dataset:{image:cfg.images[0]},querySelectorAll:()=>[input],querySelector:selector=>({checked:selector==='[data-include]'||unknown})};
  const nodes={'review-config':{textContent:JSON.stringify(cfg)},'download-answers':{addEventListener:(type,fn)=>{assert.equal(type,'click');callback=fn;}},'review-message':message,reviewer:{value:'me'},'review-method':{value:'independent_reading'}};
  const link={click:()=>{clicked=true;},remove:()=>{}};
  const context={document:{getElementById:id=>nodes[id],querySelectorAll:()=>[field],createElement:()=>link,body:{appendChild:()=>{}}},Blob,URL:{createObjectURL:b=>{blob=b;return 'blob:fixture';},revokeObjectURL:url=>{assert.equal(url,'blob:fixture');revoked=true;}},setTimeout:fn=>fn()};
  vm.runInNewContext(fs.readFileSync(require.resolve("""+json.dumps(str(self.script))+"""),'utf8'),context);
  assert.equal(clicked,false);callback();assert.equal(clicked,true);assert.equal(revoked,true);
  assert.match(link.download,/^aiedge-answers-a{12}[.]json$/);assert.match(message.textContent,/Check your downloads/);
  blob.text().then(text=>{const saved=JSON.parse(text);assert.equal(saved.images[0].readings.main,null);assert.equal(saved.review_sha256,cfg.review_sha256);});
  clicked=false;input.value='';callback();assert.equal(clicked,false);assert.match(message.textContent,/Enter a number/);unknown=true;callback();assert.equal(clicked,true);
  """)
 def test_dial_validation_before_output(self):
  for dials in [[],['a']*2,['x-y'],['<script>'],['x'*65],['d'+str(i) for i in range(17)],'main']:
   with self.assertRaises(ValueError):self.f.generate(dials=dials)
   self.assertFalse(self.f.output.exists())
 def test_default_gallery_stays_view_only(self):
  self.f.generate();page=(self.f.output/'index.html').read_text(encoding='utf-8')
  self.assertNotIn('download-answers',page);self.assertNotIn('label_form_dials',json.loads((self.f.output/'review.json').read_text(encoding='utf-8')))

if __name__=='__main__':unittest.main()
