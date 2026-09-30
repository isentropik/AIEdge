"""Proposals cannot overwrite calibration or enter a configured moving dial crop."""
import io,itertools,os,unittest
from PIL import Image
from marker_suggestions import propose,MIN_DISTANCE,MIN_AREA
from test_synthetic_pipeline import generated_fixture
from calibration_builder import build

class SuggestionTests(unittest.TestCase):
    def test_generated_texture_peaks_are_spread_outside_dials_and_deterministic(self):
        blob,calibration=generated_fixture();crops=[d['crop'] for d in calibration['dials']]
        result=propose(blob,crops);self.assertFalse(result['automatic_calibration']);self.assertEqual(result,propose(blob,crops))
        self.assertEqual(len(result['markers']),3,result)
        centers=[]
        for x,y,w,h in result['markers']:
            centers.append((x+w/2,y+h/2))
            for cx,cy,cw,ch in crops:self.assertTrue(x+w<=cx-4 or x>=cx+cw+4 or y+h<=cy-4 or y>=cy+ch+4)
        for a,b in itertools.combinations(centers,2):self.assertGreaterEqual((a[0]-b[0])**2+(a[1]-b[1])**2,MIN_DISTANCE**2)
        a,b,c=centers;self.assertGreaterEqual(abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))/2,MIN_AREA)
    def test_uniform_image_does_not_invent_three_markers(self):
        stream=io.BytesIO();Image.new('RGB',(640,480),'white').save(stream,format='PNG')
        result=propose(stream.getvalue(),[[100,100,140,140]])
        self.assertEqual(result['markers'],[]);self.assertIn('manually',result['reason'])
    def test_invalid_or_missing_moving_regions_rejected(self):
        blob,_=generated_fixture()
        for crops in (None,[],[[100,100,140,140]]*17,[[0,0,640,480]],[[True,100,140,140]],[None]):
            with self.subTest(crops=crops),self.assertRaises(ValueError):propose(blob,crops)
    def test_malformed_or_wrong_size_reference_rejected(self):
        with self.assertRaises(ValueError):propose(b'broken',[[100,100,140,140]])
        stream=io.BytesIO();Image.new('RGB',(320,240),'gray').save(stream,format='JPEG')
        with self.assertRaisesRegex(ValueError,'640x480'):propose(stream.getvalue(),[[100,100,140,140]])
    @unittest.skipUnless(os.environ.get('AIEDGE_NATIVE_LIBRARY') and os.environ.get('AIEDGE_MODELS_FIXTURE'),'native/models required')
    def test_suggested_generated_templates_pass_actual_pipeline_without_accuracy_claim(self):
        from reader import Reader
        blob,old=generated_fixture();result=propose(blob,[d['crop'] for d in old['dials']])
        design={'markers':result['markers'],'dials':[{**d,**d['landmarks']} for d in old['dials']]}
        document,_=build(blob,design);reader=Reader(os.environ['AIEDGE_NATIVE_LIBRARY'],os.environ['AIEDGE_MODELS_FIXTURE'],document)
        try:
            result=reader.read_jpeg(blob);self.assertEqual(result['state'],'estimated',result)
            self.assertFalse(result['accuracy_verified']);self.assertFalse(result['training_allowed'])
        finally:reader.runtime.close()

if __name__=='__main__':unittest.main()
