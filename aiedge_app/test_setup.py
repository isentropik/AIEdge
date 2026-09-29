import copy,hashlib,io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from calibration_builder import build
from setup_store import Setup
from recognition import Recognition
from capture import Store

DESIGN={'markers':[[20,20,20,20],[400,20,20,20],[200,400,20,20]],'dials':[{'name':'Dial 1','model':'main','direction':'cw','crop':[100,100,140,140],'rim_points':[[170,110],[230,170],[170,230],[110,170]],'needle_pivot':[171,169]}]}
def reference():
    out=io.BytesIO();Image.new('RGB',(640,480),'white').save(out,format='PNG');return out.getvalue()
class Candidate:
    def __init__(self,document):self.pipeline_id=hashlib.sha256(json.dumps(document,sort_keys=True).encode()).hexdigest()
    def read_rgb(self,rgb):return {'state':'estimated'}
class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);self.worker=Recognition(self.store)
        self.setup=Setup(self.temp.name,Candidate,self.worker);self.ref=self.setup.add_reference(reference())
    def tearDown(self):self.temp.cleanup()
    def test_malformed_reference_and_landmarks_preserve_setup(self):
        saved=self.setup.save(self.ref,DESIGN,None);before=self.setup.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'reference_image_unreadable'):
            self.setup.add_reference(b'not an image')
        for bad in (None,True,10**400,float('inf')):
            changed=copy.deepcopy(DESIGN);changed['dials'][0]['needle_pivot']=[bad,120]
            with self.subTest(bad_type=type(bad).__name__):
                with self.assertRaisesRegex(ValueError,'invalid_landmark'):
                    self.setup.save(self.ref,changed,saved['revision'])
        changed=copy.deepcopy(DESIGN);changed['dials']=[None]
        with self.assertRaisesRegex(ValueError,'invalid_dial_geometry'):
            self.setup.save(self.ref,changed,saved['revision'])
        changed=copy.deepcopy(DESIGN);changed['dials']*=17
        with self.assertRaisesRegex(ValueError,'invalid_dial_count'):
            self.setup.save(self.ref,changed,saved['revision'])
        self.assertEqual(self.setup.path.read_bytes(),before)
        self.assertEqual(self.setup.status(),saved)
    def test_explicit_pivot_not_crop_center(self):
        d,_=build(reference(),DESIGN);dial=d['dials'][0]
        expected=[60,0,70,0,60,70,0,0,1]
        for a,b in zip(dial['inverse'],expected):self.assertAlmostEqual(a,b)
        self.assertAlmostEqual(dial['pivot'][0],1/60);self.assertAlmostEqual(dial['pivot'][1],-1/60)
    def test_crossed_and_outside_landmarks_rejected(self):
        d=copy.deepcopy(DESIGN);d['dials'][0]['rim_points'][1],d['dials'][0]['rim_points'][2]=d['dials'][0]['rim_points'][2],d['dials'][0]['rim_points'][1]
        with self.assertRaisesRegex(ValueError,'clockwise'):build(reference(),d)
        d=copy.deepcopy(DESIGN);d['dials'][0]['needle_pivot']=[1,1]
        with self.assertRaisesRegex(ValueError,'outside_crop'):build(reference(),d)
    def test_activation_restart_and_revision_conflict(self):
        self.assertEqual(self.worker.latest()['state'],'not_configured')
        saved=self.setup.save(self.ref,DESIGN,None);pipeline=self.worker.reader.pipeline_id
        new=Setup(self.temp.name,Candidate,Recognition(self.store));self.assertEqual(new.status(),saved)
        with self.assertRaisesRegex(ValueError,'changed'):self.setup.save(self.ref,DESIGN,None)
        self.assertEqual(self.worker.reader.pipeline_id,pipeline);self.assertEqual(self.store.status()['captures'],0)
    def test_failed_write_preserves_active(self):
        saved=self.setup.save(self.ref,DESIGN,None);original=self.setup.path.read_bytes();pipeline=self.worker.reader.pipeline_id
        changed=copy.deepcopy(DESIGN);changed['dials'][0]['name']='Changed'
        with patch.object(self.setup,'_atomic',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.setup.save(self.ref,changed,saved['revision'])
        self.assertEqual(self.setup.path.read_bytes(),original);self.assertEqual(self.worker.reader.pipeline_id,pipeline)
        self.assertEqual(self.setup.status(),saved)
    def test_preflight_failure_preserves_active(self):
        saved=self.setup.save(self.ref,DESIGN,None);original=self.setup.path.read_bytes()
        with patch.object(Candidate,'read_rgb',return_value={'state':'rejected','error':'alignment_rejected'}):
            with self.assertRaisesRegex(ValueError,'reference_recognition_rejected'):self.setup.save(self.ref,DESIGN,saved['revision'])
        self.assertEqual(self.setup.path.read_bytes(),original)
    def test_reference_corruption_and_copy_isolation(self):
        saved=self.setup.save(self.ref,DESIGN,None);saved['calibration']['dials'][0]['name']='bad'
        self.assertEqual(self.setup.status()['calibration']['dials'][0]['name'],'Dial 1')
        (self.setup.references/(self.ref+'.image')).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'reference_corrupt'):self.setup.save(self.ref,DESIGN,saved['revision'])
if __name__=='__main__':unittest.main()
