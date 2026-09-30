"""Review edits preserve images, inference, split flags and previous human entries."""
import copy,hashlib,json,sqlite3,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from capture import Store
from review_store import Reviews,ReviewConflict
from test_capture import JPEG,headers

def runtime():
    document={'reference_sha256':'b'*64,'dials':[{'name':'Dial 1','direction':'ccw','model':'main','needle_pivot':{'x':12,'y':15}}]}
    return SimpleNamespace(lock=threading.Lock(),reader=SimpleNamespace(pipeline_id='a'*64,profile='fixture',runtime=SimpleNamespace(document=document),dials=document['dials']))

class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.store=Store(self.root)
        self.store.add('fixture',JPEG,headers('first',JPEG));self.worker=runtime();self.reviews=Reviews(self.store,self.worker)
    def tearDown(self):self.temp.cleanup()
    def payload(self,value=5.1,event=1):
        state=self.reviews.get(event)
        return {'event_id':event,'context_id':state['context']['id'],'revision':state['review']['revision'] if state['review'] else None,'positions':[value]}
    def test_review_preserves_raw_capture_inference_and_training_exclusion(self):
        with self.store.connect() as db:
            db.execute('CREATE TABLE inference(sha256 TEXT,pipeline TEXT,result TEXT)')
            db.execute('INSERT INTO inference VALUES(?,?,?)',(hashlib.sha256(JPEG).hexdigest(),'fixture','model estimate only'))
            before=db.execute('SELECT * FROM frames').fetchall()
        saved=self.reviews.save(self.payload())
        self.assertEqual(saved['positions'],[5.1]);self.assertEqual(saved['provenance'],'human_entered')
        self.assertFalse(saved['training_allowed']);self.assertFalse(saved['accuracy_verified'])
        self.assertEqual(self.store.image(saved['sha256']),JPEG)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT * FROM frames').fetchall(),before)
            self.assertEqual(db.execute('SELECT result FROM inference').fetchone()[0],'model estimate only')
    def test_unknown_and_zero_are_distinct_and_restart_preserves_revision(self):
        a=self.reviews.save(self.payload(None));self.assertEqual(a['positions'],[None])
        b=self.reviews.save(self.payload(0));self.assertEqual(b['positions'],[0]);self.assertEqual(b['previous_revision'],a['revision'])
        self.assertEqual(Reviews(Store(self.root),self.worker).get(1)['review'],b)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM human_reviews').fetchone()[0],2)
    def test_duplicate_images_share_one_review_and_no_new_accuracy_evidence(self):
        self.store.add('fixture',JPEG,headers('second',JPEG));saved=self.reviews.save(self.payload())
        state=self.reviews.get(2);self.assertEqual(state['review'],saved);self.assertEqual(state['capture']['matching_captures'],2)
        self.assertFalse(state['accuracy_verified']);self.assertEqual(self.store.status()['unique_images'],1)
    def test_different_image_does_not_inherit_labels(self):
        self.reviews.save(self.payload());blob=b'\xff\xd8other image\xff\xd9'
        self.store.add('fixture',blob,headers('other',blob));self.assertIsNone(self.reviews.get(2)['review'])
    def test_calibration_or_model_changes_reject_stale_save_and_preserve_snapshot(self):
        initial=self.reviews.save(self.payload());payload=self.payload(5.2)
        self.worker.reader.runtime.document['dials'][0]['needle_pivot']['x']=20
        with self.assertRaises(ReviewConflict):self.reviews.save(payload)
        current=self.reviews.get(1);self.assertIsNone(current['review']);self.assertEqual(current['other_context_reviews'],1)
        self.assertEqual(initial['context']['calibration']['dials'][0]['needle_pivot']['x'],12)
        self.worker.reader.pipeline_id='c'*64
        self.assertNotEqual(self.reviews.get(1)['context']['id'],current['context']['id'])
    def test_two_tabs_cannot_overwrite_each_other(self):
        first=self.payload(5.1);second=self.payload(5.2)
        self.reviews.save(first)
        with self.assertRaises(ReviewConflict):self.reviews.save(second)
        self.assertEqual(self.reviews.get(1)['review']['positions'],[5.1])
    def test_repeat_submission_with_current_revision_is_idempotent(self):
        first=self.reviews.save(self.payload());second=self.reviews.save(self.payload())
        self.assertEqual(first,second)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM human_reviews').fetchone()[0],1)
    def test_concurrent_saves_admit_one_revision(self):
        payload=self.payload();other=Reviews(Store(self.root),runtime());barrier=threading.Barrier(2);results=[]
        def run(reviews):
            barrier.wait()
            try:results.append(reviews.save(payload)['revision'])
            except ReviewConflict:results.append('conflict')
        threads=[threading.Thread(target=run,args=(review,)) for review in (self.reviews,other)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(10);self.assertFalse(thread.is_alive())
        self.assertEqual(results.count('conflict'),1);self.assertEqual(len(results),2)
    def test_invalid_values_and_structure_leave_no_partial_write(self):
        for value in (True,'5',-0.1,10,10**400,float('nan'),float('inf'),{},[]):
            with self.subTest(value=value),self.assertRaises(ValueError):self.reviews.save(self.payload(value))
        for replacement in ({'event_id':True},{'revision':'bad'},{'positions':[]},{'positions':[1,2]},{'extra':1}):
            payload=self.payload();payload.update(replacement)
            with self.subTest(replacement=replacement),self.assertRaises(ValueError):self.reviews.save(payload)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM human_reviews').fetchone()[0],0)
    def test_image_missing_or_corrupt_prevents_admission(self):
        payload=self.payload();path=next((self.root/'images').glob('*.jpg'));path.write_bytes(b'broken')
        with self.assertRaisesRegex(ValueError,'stored_image_corrupt'):self.reviews.save(payload)
        path.unlink()
        with self.assertRaises(FileNotFoundError):self.reviews.save(payload)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM human_reviews').fetchone()[0],0)
    def test_missing_runtime_and_capture_have_explicit_failures(self):
        reviews=Reviews(self.store,None);self.assertIsNone(reviews.get(1)['context'])
        with self.assertRaises(ReviewConflict):reviews.save(self.payload())
        with self.assertRaises(FileNotFoundError):self.reviews.get(2)
        for value in (True,0,-1,2**63):
            with self.assertRaises(ValueError):self.reviews.get(value)
    def test_history_is_append_only_and_invalid_record_is_preserved(self):
        self.reviews.save(self.payload())
        with self.store.connect() as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('UPDATE human_reviews SET document=?',('{}',))
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM human_reviews')
            db.execute('DROP TRIGGER human_reviews_no_update');db.execute('UPDATE human_reviews SET document=?',('{}',))
        with self.assertRaisesRegex(ValueError,'integrity check'):self.reviews.get(1)
        rows=self.store.history()['items'];self.reviews.summaries(rows)
        self.assertTrue(rows[0]['review_error']);self.assertIsNone(rows[0]['reviewed_dials'])
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT document FROM human_reviews').fetchone()[0],'{}')
    def test_get_context_is_a_copy_and_history_counts_confirmed_dials(self):
        state=self.reviews.get(1);state['context']['dials'][0]['name']='Changed';state['context']['calibration']['dials'][0]['needle_pivot']['x']=100
        self.assertEqual(self.worker.reader.dials[0]['name'],'Dial 1')
        self.assertEqual(self.worker.reader.runtime.document['dials'][0]['needle_pivot']['x'],12)
        self.reviews.save(self.payload());rows=self.store.history()['items'];self.reviews.summaries(rows)
        self.assertEqual((rows[0]['reviewed_dials'],rows[0]['review_dials']),(1,1));self.assertFalse(rows[0]['training_allowed'])

if __name__=='__main__':unittest.main()
