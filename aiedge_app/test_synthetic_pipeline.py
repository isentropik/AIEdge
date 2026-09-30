"""Generated geometry and both real models; never photograph labels or accuracy."""
import hashlib,io,math,os,random,tempfile,unittest
from datetime import datetime,timedelta,timezone
from PIL import Image,ImageDraw
from calibration_builder import build
from capture import Store
from consumption import Consumption
from reader import Reader
from recognition import Recognition
from reading_format import FormatStore

REQUIRED=('AIEDGE_NATIVE_LIBRARY','AIEDGE_MODELS_FIXTURE','AIEDGE_ACCOUNTING_LIBRARY')
def generated_fixture():
    image=Image.new('RGB',(640,480),(220,220,220));draw=ImageDraw.Draw(image)
    randomizer=random.Random(104729);markers=[[30,30,24,24],[550,35,24,24],[45,405,24,24]]
    for x,y,w,h in markers:
        for yy in range(y,y+h):
            for xx in range(x,x+w):
                value=randomizer.randrange(256);draw.point((xx,yy),fill=(value,value,value))
    dials=[]
    for index,(x,y) in enumerate(((170,170),(430,170))):
        draw.ellipse((x-60,y-60,x+60,y+60),fill='white',outline='black',width=2)
        for i in range(20):
            angle=i*math.pi/10
            draw.line((x+math.sin(angle)*52,y-math.cos(angle)*52,x+math.sin(angle)*58,y-math.cos(angle)*58),fill='black',width=1)
        draw.polygon(((x-8,y+18),(x-8,y-15),(x,y-48),(x+8,y-15),(x+8,y+18)),fill='black')
        draw.ellipse((x-5,y-5,x+5,y+5),fill='black')
        dials.append({'name':'Generated '+str(index+1),'model':'main' if index==0 else 'secondary','direction':'cw',
                      'crop':[x-70,y-70,140,140],'rim_points':[[x,y-60],[x+60,y],[x,y+60],[x-60,y]],'needle_pivot':[x,y]})
    stream=io.BytesIO();image.save(stream,format='JPEG',quality=95);blob=stream.getvalue()
    document,_=build(blob,{'markers':markers,'dials':dials})
    return blob,document

@unittest.skipUnless(all(os.environ.get(k) for k in REQUIRED),'native/model/accounting libraries required')
class GeneratedPipelineTests(unittest.TestCase):
    def setUp(self):
        self.blob,self.document=generated_fixture()
        self.reader=Reader(os.environ['AIEDGE_NATIVE_LIBRARY'],os.environ['AIEDGE_MODELS_FIXTURE'],self.document)
    def tearDown(self):self.reader.runtime.close()
    def test_both_model_routes_estimate_without_accuracy_or_label_claims(self):
        result=self.reader.read_jpeg(self.blob)
        self.assertEqual(result['state'],'estimated',result)
        self.assertEqual(set(result['model_hashes']),{'main','secondary'})
        self.assertEqual(len(result['dial_positions']),2)
        for dial in result['dial_positions']:
            self.assertEqual(dial['state'],'estimated');self.assertTrue(0<=dial['position']<10)
            self.assertRegex(dial['scores_sha256'],'^[a-f0-9]{64}$')
        self.assertFalse(result['accuracy_verified']);self.assertFalse(result['training_allowed'])
        self.assertIsNone(result['physical_value'])
        # No exact needle value is asserted: these are generated images, not accuracy evidence.
    def test_missing_generated_markers_is_rejected(self):
        stream=io.BytesIO();Image.new('RGB',(640,480),'white').save(stream,format='JPEG')
        result=self.reader.read_jpeg(stream.getvalue())
        self.assertEqual(result['state'],'rejected');self.assertEqual(result['error'],'alignment_rejected')
        self.assertFalse(result['accuracy_verified']);self.assertFalse(result['training_allowed'])
    def test_actual_model_estimates_persist_and_stationary_capture_cannot_add_consumption(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);recognition=Recognition(store,self.reader);formats=FormatStore(directory,recognition)
            formats.save({'version':1,'pipeline_id':self.reader.pipeline_id,'unit':'ft3','maximum_rate_per_second':.05,
                          'dials':[{'index':i,'value_per_revolution':v,'position_error':.1} for i,v in enumerate((1000,5))]},None)
            worker=Consumption(store,recognition,formats,os.environ['AIEDGE_ACCOUNTING_LIBRARY'])
            digest=hashlib.sha256(self.blob).hexdigest();base=datetime.now(timezone.utc)-timedelta(minutes=5)
            try:
                for i in range(3):
                    store.add('generated-fixture',self.blob,{'X-AIEdge-Frame-Id':'generated-'+str(i),
                              'X-AIEdge-Captured-At':(base+timedelta(seconds=i*30)).isoformat(),
                              'X-AIEdge-SHA256':digest,'X-AIEdge-Clock-Id':'simulated-generated-boot',
                              'X-AIEdge-Capture-Monotonic-Us':str(1000000+i*30000000)})
                    self.assertEqual(recognition.once(),i==0)
                    while worker.once():pass
                state=worker.status();self.assertEqual(state['state'],'within_noise');self.assertIsNone(state['value'])
                self.assertFalse(state['accuracy_verified']);self.assertFalse(state['training_allowed'])
                self.assertEqual(store.status()['captures'],3);self.assertEqual(store.status()['unique_images'],1)
                result=recognition.latest();restored=Recognition(Store(directory),self.reader)
                self.assertEqual(restored.latest(),result)
                worker._drop();worker=Consumption(store,restored,FormatStore(directory,restored),os.environ['AIEDGE_ACCOUNTING_LIBRARY'])
                while worker.once():pass
                self.assertEqual(worker.status(),state)
                with store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM consumption_records').fetchone()[0],3)
            finally:worker._drop()

if __name__=='__main__':unittest.main()
