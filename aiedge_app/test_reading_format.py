import copy, os, unittest
from native import Native
from reading_format import ReadingFormat, validate, display_reading

PIPELINE='a'*64

def document(scales,errors=None):
    return {'version':1,'pipeline_id':PIPELINE,'unit':'ft3','dials':[
        {'index':i,'value_per_revolution':scale,'position_error':(errors or [.01]*len(scales))[i]}
        for i,scale in enumerate(scales)]}
def observation(positions):
    return {'state':'estimated','pipeline_id':PIPELINE,'dial_positions':[
        {'state':'estimated','position':p} for p in positions]}

class ValidationTests(unittest.TestCase):
    def test_invalid_formats_and_duplicate_dials(self):
        cases=[]
        for scale in (0,-1,float('nan'),float('inf'),True,10**400,1e-320):
            d=document([1000]);d['dials'][0]['value_per_revolution']=scale;cases.append(d)
        for error in (-1,.5,float('nan'),True):
            d=document([1000]);d['dials'][0]['position_error']=error;cases.append(d)
        d=document([1000,100]);d['dials'][1]['index']=0;cases.append(d)
        cases.extend([document([100,100]),document([100,1000]),document([100,30])])
        for d in cases:
            with self.subTest(document=d):
                with self.assertRaises(ValueError):validate(d)
    def test_display_preserves_leading_zero_and_derives_precision(self):
        self.assertEqual(display_reading(255310,document([10000000,1000000,100000,10000,1000])), '0255310')
        self.assertEqual(display_reading(109.5,document([1000,5])), '109.50')
        self.assertEqual(display_reading(999.999,document([1000,5])), '000.00')
    def test_identity_includes_interpretation_and_bounds(self):
        original=document([1000,5]);_,identity=validate(original)
        for field,value in [('unit','m3'),('pipeline_id','b'*64)]:
            changed=copy.deepcopy(original);changed[field]=value
            self.assertNotEqual(validate(changed)[1],identity)
        changed=copy.deepcopy(original);changed['dials'][0]['position_error']=.02
        self.assertNotEqual(validate(changed)[1],identity)

@unittest.skipUnless(os.environ.get('AIEDGE_READING_LIBRARY'),'reading native library required')
class CalculationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.native=Native(os.environ['AIEDGE_READING_LIBRARY'])
    def evaluate(self,scales,positions,errors=None):
        return ReadingFormat(self.native,document(scales,errors)).evaluate(observation(positions))
    def test_lower_dial_replaces_fraction_not_adds(self):
        result=self.evaluate([1000,100,10],[1.234,2.34,3.4])
        self.assertEqual(result['state'],'estimated');self.assertAlmostEqual(result['value'],123.4)
        self.assertFalse(result['accuracy_verified']);self.assertFalse(result['training_allowed'])
    def test_carry_across_multiple_dials_and_register_wrap(self):
        for value in (0,99.9,100.1,999.9,.1):
            scales=[1000,100,10]
            result=self.evaluate(scales,[(value%s)/s*10 for s in scales])
            self.assertEqual(result['state'],'estimated');self.assertAlmostEqual(result['value'],value)
    def test_five_unit_wheel_ratio_and_ambiguous_turns(self):
        result=self.evaluate([1000,5],[1.095,9.0],[.01,.01])
        self.assertEqual(result['state'],'estimated');self.assertAlmostEqual(result['value'],109.5)
        result=self.evaluate([1000,5],[1.095,9.0],[.1,.01])
        self.assertEqual(result['state'],'ambiguous');self.assertIsNone(result['value'])
    def test_contradiction_never_published(self):
        result=self.evaluate([1000,100],[1.2,8.0])
        self.assertEqual(result['state'],'inconsistent');self.assertIsNone(result['value'])
    def test_stale_pipeline_missing_dial_and_rejected_image(self):
        reader=ReadingFormat(self.native,document([1000,100]))
        bad=observation([1.2,2]);bad['pipeline_id']='b'*64
        self.assertEqual(reader.evaluate(bad)['reason'],'reading_pipeline_changed')
        self.assertEqual(reader.evaluate(observation([1.2]))['reason'],'reading_dial_mapping_mismatch')
        bad=observation([1.2,2]);bad['dial_positions'][1]['state']='rejected'
        self.assertEqual(reader.evaluate(bad)['reason'],'dial_unavailable')
        self.assertEqual(reader.evaluate({'state':'waiting_for_image'})['reason'],'image_unavailable')
        self.assertEqual(reader.evaluate({'state':'pending'})['reason'],'image_unavailable')
        bad=observation([1.2,2]);bad['state']='rejected'
        self.assertEqual(reader.evaluate(bad)['reason'],'image_unavailable')
    def test_display_order_can_differ_from_value_order(self):
        d=document([1000,100]);d['dials'][0]['index']=1;d['dials'][1]['index']=0
        result=ReadingFormat(self.native,d).evaluate(observation([2,1.2]))
        self.assertEqual(result['state'],'estimated');self.assertAlmostEqual(result['value'],120)
    def test_unknown_and_nonfinite_positions(self):
        for value in (None,-1,10,float('inf'),float('nan'),True):
            result=self.evaluate([1000],[value]);self.assertIsNone(result['value'])
            self.assertEqual(result['reason'],'dial_unavailable')

@unittest.skipUnless(os.environ.get('AIEDGE_READING_LIBRARY'),'reading native library required')
class PersistenceTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from types import SimpleNamespace
        from capture import Store
        from recognition import Recognition
        from reading_format import FormatStore
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(self.temp.name)
        self.reader=SimpleNamespace(pipeline_id=PIPELINE,native=Native(os.environ['AIEDGE_READING_LIBRARY']),
                                    dials=[{'name':'Dial 1','direction':'ccw'},{'name':'Dial 2','direction':'cw'}])
        self.worker=Recognition(self.store,self.reader)
        self.formats=FormatStore(self.temp.name,self.worker)
    def tearDown(self):self.temp.cleanup()
    def test_save_restart_and_changed_pipeline(self):
        from reading_format import FormatStore
        saved=self.formats.save(document([1000,100]),None)
        restored=FormatStore(self.temp.name,self.worker)
        self.assertEqual(restored.status(),saved)
        self.assertAlmostEqual(restored.evaluate(observation([1.2,2]))['value'],120)
        self.reader.pipeline_id='b'*64
        self.assertIsNone(restored.evaluate(observation([1.2,2]))['value'])
        with self.assertRaisesRegex(ValueError,'pipeline_changed'):restored.save(document([1000,100]),saved['revision'])
    def test_revision_and_failed_write_preserve_saved_format(self):
        from unittest.mock import patch
        saved=self.formats.save(document([1000,100]),None);before=self.formats.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'changed_reload'):self.formats.save(document([1000,100]),None)
        with patch('setup_store.Setup._atomic',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.formats.save(document([1000,100]),saved['revision'])
        self.assertEqual(self.formats.path.read_bytes(),before);self.assertEqual(self.formats.status(),saved)
    def test_http_format_save_and_status(self):
        import json,threading,urllib.request,urllib.error
        from http.server import ThreadingHTTPServer
        from types import SimpleNamespace
        from service import handler
        # Setup token is shared by the calibration and format APIs.
        setup=SimpleNamespace(status=lambda:{'revision':None,'calibration':None})
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.store,False,None,self.worker,setup,self.formats))
        thread=threading.Thread(target=server.serve_forever);thread.start()
        origin=f'http://127.0.0.1:{server.server_port}'
        try:
            with urllib.request.urlopen(origin+'/api/setup') as r:token=json.load(r)['token']
            with urllib.request.urlopen(origin+'/api/reading-format') as r:state=json.load(r)
            self.assertEqual(state['pipeline_id'],PIPELINE);self.assertEqual(len(state['dials']),2)
            body=json.dumps({'format':document([1000,100]),'revision':None}).encode()
            request=urllib.request.Request(origin+'/api/reading-format',data=body,headers={'Content-Type':'application/json'})
            with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(request)
            self.assertEqual(caught.exception.code,403);caught.exception.close()
            request.add_header('X-AIEdge-Setup',token)
            with urllib.request.urlopen(request) as r:saved=json.load(r)
            self.assertEqual(saved,self.formats.status())
            with urllib.request.urlopen(origin+'/api/status') as r:state=json.load(r)
            self.assertIsNone(state['reading']['value'])
            self.assertEqual(state['reading']['state'],'unavailable')
            from test_capture import JPEG,headers
            from capture import now
            self.store.add('fixture',JPEG,headers())
            digest=self.store.status()['latest']['sha256']
            with self.store.connect() as db:
                db.execute('INSERT INTO inference VALUES(?,?,?,?)',(digest,PIPELINE,now(),json.dumps(dict(observation([1.2,2]),source_sha256=digest,training_allowed=False,accuracy_verified=False))))
            with urllib.request.urlopen(origin+'/api/status') as r:state=json.load(r)
            self.assertEqual(state['reading']['state'],'estimated')
            self.assertAlmostEqual(state['reading']['value'],120)
            self.assertFalse(state['reading']['accuracy_verified'])
        finally:server.shutdown();thread.join();server.server_close()

if __name__=='__main__':unittest.main()
