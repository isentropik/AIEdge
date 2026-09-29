"""Run with AIEDGE_NATIVE_LIBRARY, AIEDGE_CALIBRATION_FIXTURE and AIEDGE_RGB_FIXTURE."""
import copy,json,os,unittest
from pathlib import Path
from native import Native,Profile
from calibration import load

@unittest.skipUnless(all(os.environ.get(k) for k in ('AIEDGE_NATIVE_LIBRARY','AIEDGE_CALIBRATION_FIXTURE','AIEDGE_RGB_FIXTURE')),'native fixture paths not supplied')
class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.native=Native(os.environ['AIEDGE_NATIVE_LIBRARY'])
        cls.document,_=load(os.environ['AIEDGE_CALIBRATION_FIXTURE'])
        cls.rgb=Path(os.environ['AIEDGE_RGB_FIXTURE']).read_bytes()
    def test_dense_and_sparse_match_frozen(self):
        p=Profile(self.native,self.document)
        try:
            for sparse in (False,True):self.assertEqual(p.prepare(self.rgb,sparse),self.native.prepare(self.rgb,sparse))
        finally:p.close()
    def test_geometry_and_markers_rejected(self):
        for kind in ('off_frame','singular','pivot_outside','marker_overlap','marker_target_duplicate','template_hash'):
            with self.subTest(kind=kind):
                bad=copy.deepcopy(self.document)
                if kind=='off_frame':bad['dials'][0]['crop'][0]=639
                if kind=='singular':bad['dials'][0]['inverse']=[0]*9
                if kind=='pivot_outside':bad['dials'][0]['pivot']=[10,10]
                if kind=='marker_overlap':bad['markers'][1]=copy.deepcopy(bad['markers'][0])
                if kind=='marker_target_duplicate':bad['markers'][1]['target']=bad['markers'][0]['target']
                if kind=='template_hash':bad['markers'][0]['sha256']='0'*64
                with self.assertRaises(ValueError):Profile(self.native,bad)
    def test_owns_candidate_and_rejects_closed_handle(self):
        candidate=copy.deepcopy(self.document);p=Profile(self.native,candidate)
        candidate['dials'][0]['inverse']=[0]*9;candidate['markers'][0]['pixels']=''
        self.assertEqual(p.prepare(self.rgb),self.native.prepare(self.rgb))
        p.close();p.close()
        with self.assertRaisesRegex(ValueError,'closed'):p.prepare(self.rgb)
    def test_reordered_subset(self):
        candidate=copy.deepcopy(self.document);candidate['dials']=[candidate['dials'][4],candidate['dials'][1]]
        p=Profile(self.native,candidate)
        try:
            expected=self.native.prepare(self.rgb)
            self.assertEqual(p.prepare(self.rgb),[expected[4],expected[1]])
        finally:p.close()
    def test_blank_image_rejected(self):
        p=Profile(self.native,self.document)
        try:
            with self.assertRaisesRegex(ValueError,'alignment_rejected'):p.prepare(bytes(640*480*3))
        finally:p.close()
if __name__=='__main__':unittest.main()
