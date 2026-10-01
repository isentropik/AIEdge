"""Exact reuse versus full processing, including changed pixels and rejected frames."""
import io,os,unittest
from PIL import Image,ImageDraw
from native import Native,Profile
from reader import Reader
from test_synthetic_pipeline import generated_fixture

@unittest.skipUnless(all(os.environ.get(k) for k in ('AIEDGE_NATIVE_LIBRARY','AIEDGE_MODELS_FIXTURE')),'native and model fixtures required')
class ChangedDialTests(unittest.TestCase):
    def setUp(self):
        self.blob,self.document=generated_fixture()
        with Image.open(io.BytesIO(self.blob)) as im:self.image=im.convert('RGB')
        self.rgb=self.image.tobytes();self.native=Native(os.environ['AIEDGE_NATIVE_LIBRARY'])
        self.cached=Profile(self.native,self.document);self.full=Profile(self.native,self.document)
        self.addCleanup(self.cached.close);self.addCleanup(self.full.close)
    def check(self,rgb,sparse=True):
        actual=self.cached.prepare_with_reuse(rgb,sparse);expected=self.full.prepare(rgb,sparse)
        self.assertEqual([{k:v for k,v in row.items() if k!='reused'} for row in actual],expected)
        return actual
    def changed(self,x,y):
        im=self.image.copy();pixel=im.getpixel((x,y));im.putpixel((x,y),tuple(255-v for v in pixel));return im.tobytes()
    def test_identical_dials_skip_extraction_and_match_full_features(self):
        self.assertEqual([r['reused'] for r in self.check(self.rgb)],[False,False])
        self.assertEqual([r['reused'] for r in self.check(self.rgb)],[True,True])
    def test_changed_dial_only_recomputes_its_crop(self):
        self.check(self.rgb)
        self.assertEqual([r['reused'] for r in self.check(self.changed(170,150))],[False,True])
    def test_background_changes_do_not_force_unchanged_dial_extraction(self):
        self.check(self.rgb)
        self.assertEqual([r['reused'] for r in self.check(self.changed(300,300))],[True,True])
    def test_bicubic_source_halo_is_included_in_change_check(self):
        self.check(self.rgb)
        # A tap just outside the first crop can affect its interpolated edge.
        self.assertEqual([r['reused'] for r in self.check(self.changed(99,130))],[False,True])
    def test_alignment_failure_clears_all_reuse(self):
        self.check(self.rgb);self.check(self.rgb)
        with self.assertRaisesRegex(ValueError,'alignment_rejected'):self.cached.prepare_with_reuse(bytes(640*480*3))
        self.assertEqual([r['reused'] for r in self.check(self.rgb)],[False,False])
    def test_sampling_mode_change_recomputes_both_dials(self):
        self.check(self.rgb,True)
        self.assertEqual([r['reused'] for r in self.check(self.rgb,False)],[False,False])
        self.assertEqual([r['reused'] for r in self.check(self.rgb,False)],[True,True])
        self.assertEqual([r['reused'] for r in self.check(self.rgb,True)],[False,False])
    def test_changed_alignment_recomputes_even_when_the_scene_only_translates(self):
        self.check(self.rgb)
        shifted=self.image.transform(self.image.size,Image.Transform.AFFINE,(1,0,-5,0,1,-3),resample=Image.Resampling.NEAREST,fillcolor=(220,220,220)).tobytes()
        rows=self.check(shifted);self.assertEqual([r['reused'] for r in rows],[False,False])
        self.assertEqual([r['reused'] for r in self.check(shifted)],[True,True])
    def test_invisible_dial_is_rejected_each_frame_and_not_reused(self):
        self.check(self.rgb)
        im=self.image.copy();im.paste((220,220,220),(100,100,240,240));blank=im.tobytes()
        for _ in range(2):
            rows=self.check(blank);self.assertEqual(rows[0]['state'],'low_contrast');self.assertFalse(rows[0]['reused']);self.assertTrue(rows[1]['reused'])
        self.assertEqual([r['reused'] for r in self.check(self.rgb)],[False,True])
    def reader(self,reuse):
        r=Reader(os.environ['AIEDGE_NATIVE_LIBRARY'],os.environ['AIEDGE_MODELS_FIXTURE'],self.document,reuse_unchanged=reuse)
        self.addCleanup(r.runtime.close);return r
    def test_reader_reuses_model_outputs_only_for_identical_inputs(self):
        r=self.reader(True);full=self.reader(False)
        for blob in (self.rgb,self.rgb,self.changed(300,300),self.changed(170,150),self.rgb):
            actual=r.read_rgb(blob);expected=full.read_rgb(blob)
            for k in ('state','dial_positions','accuracy_verified','training_allowed','physical_value'):
                self.assertEqual(actual[k],expected[k])
        repeat=r.read_rgb(self.rgb)
        self.assertEqual(repeat['work'],{'dials':2,'preprocessing_reused':2,'inference_reused':2})
        self.assertFalse(repeat['accuracy_verified']);self.assertFalse(repeat['training_allowed'])
    def test_new_reader_and_failed_alignment_cannot_reuse_old_results(self):
        r=self.reader(True);r.read_rgb(self.rgb);r.read_rgb(self.rgb)
        bad=r.read_rgb(bytes(640*480*3));self.assertEqual(bad['state'],'rejected')
        fresh=r.read_rgb(self.rgb);self.assertEqual(fresh['work']['preprocessing_reused'],0);self.assertEqual(fresh['work']['inference_reused'],0)
        replacement=self.reader(True);self.assertEqual(replacement.read_rgb(self.rgb)['work']['inference_reused'],0)
    def test_disabled_reuse_runs_full_path_and_has_separate_pipeline_identity(self):
        cached=self.reader(True);full=self.reader(False);self.assertNotEqual(cached.pipeline_id,full.pipeline_id)
        for _ in range(2):self.assertEqual(full.read_rgb(self.rgb)['work'],{'dials':2,'preprocessing_reused':0,'inference_reused':0})
    def test_camera_jpeg_defaults_to_full_sampling_with_separate_sparse_identity(self):
        reader=self.reader(True)
        full=reader.read_jpeg(self.blob)
        sparse=reader.read_rgb(self.rgb,sparse=True)
        self.assertEqual(full['sampling'],'full')
        self.assertEqual(full['pipeline_id'],reader.pipeline_id)
        self.assertEqual(sparse['sampling'],'sparse')
        self.assertNotEqual(full['pipeline_id'],sparse['pipeline_id'])
        self.assertEqual(full['model_hashes'],sparse['model_hashes'])
        repeated=reader.read_jpeg(self.blob)
        self.assertEqual(repeated['pipeline_id'],full['pipeline_id'])
        self.assertEqual(repeated['dial_positions'],full['dial_positions'])
    def test_explicit_sparse_reader_and_invalid_sampling_inputs(self):
        reader=Reader(os.environ['AIEDGE_NATIVE_LIBRARY'],os.environ['AIEDGE_MODELS_FIXTURE'],
                      self.document,sampling_sparse=True)
        self.addCleanup(reader.runtime.close)
        result=reader.read_jpeg(self.blob)
        self.assertEqual(result['sampling'],'sparse')
        self.assertEqual(result['pipeline_id'],reader.pipeline_id)
        self.assertNotEqual(result['pipeline_id'],reader.read_rgb(self.rgb,sparse=False)['pipeline_id'])
        for value in (0,1,'false'):
            with self.assertRaisesRegex(ValueError,'invalid_sampling_mode'):reader.read_rgb(self.rgb,sparse=value)
    def test_failed_model_call_clears_partial_frame_outputs(self):
        r=self.reader(True);r.read_rgb(self.rgb)
        image=self.image.copy();ImageDraw.Draw(image).line((145,155,195,155),fill='black',width=5);changed=image.tobytes()
        role='main';net,inp,out=r.networks[role]
        class FailingNetwork:
            def set_tensor(self,*args):net.set_tensor(*args)
            def invoke(self):raise RuntimeError('injected_model_failure')
        r.networks[role]=(FailingNetwork(),inp,out)
        with self.assertRaisesRegex(RuntimeError,'injected_model_failure'):r.read_rgb(changed)
        r.networks[role]=(net,inp,out)
        recovered=r.read_rgb(self.rgb);self.assertEqual(recovered['state'],'estimated');self.assertEqual(recovered['work']['inference_reused'],0)

if __name__=='__main__':unittest.main()
