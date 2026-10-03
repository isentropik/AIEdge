"""Framing must not modify original captures or recognition geometry."""
import copy, hashlib, io, json, tempfile, threading, unittest, urllib.request, urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from image_edit import Edit, IDENTITY, point, strict_json
from setup_store import Setup
from recognition import Recognition
from capture import Store
from service import handler
from test_setup import Candidate, DESIGN, reference


class TransformTests(unittest.TestCase):
    def test_identity_keeps_every_pixel_and_source_hash(self):
        image=Image.new('RGB',(640,480))
        image.putdata([(x%256,y%256,(x+y)%256) for y in range(480) for x in range(640)])
        out=io.BytesIO();image.save(out,format='PNG');blob=out.getvalue();digest=hashlib.sha256(blob).hexdigest()
        result=Image.open(io.BytesIO(Edit().render(blob)))
        self.assertEqual(result.tobytes(),image.tobytes())
        self.assertEqual(hashlib.sha256(blob).hexdigest(),digest)

    def test_quarter_turns_match_independent_pillow_rotation(self):
        image=Image.new('RGB',(640,480),'black')
        for rectangle,color in [((10,10,150,100),'red'),((450,30,630,110),'green'),
                                ((430,310,625,470),'blue'),((15,340,180,465),'white')]:
            from PIL import ImageDraw
            ImageDraw.Draw(image).rectangle(rectangle,fill=color)
        out=io.BytesIO();image.save(out,format='PNG');blob=out.getvalue()
        for turns in range(4):
            with self.subTest(turns=turns):
                edit=Edit(dict(version=1,turns=turns,angle=0,crop=None))
                rendered=Image.open(io.BytesIO(edit.render(blob)))
                expected=image.rotate(-90*turns,expand=True)
                for source, color in [([80,60],(255,0,0)),([540,70],(0,128,0)),
                                      ([530,390],(0,0,255)),([90,400],(255,255,255))]:
                    view=point(edit.source_to_view,source)
                    self.assertEqual(rendered.getpixel(tuple(round(v) for v in view)),color)
                self.assertEqual(expected.size,tuple(edit.extent))
                for source in ([0,0],[640,480],[113.25,339.75],[320,240]):
                    restored=point(edit.view_to_source,point(edit.source_to_view,source))
                    for a,b in zip(source,restored):self.assertAlmostEqual(a,b,places=9)

    def test_rotated_cropped_landmarks_roundtrip(self):
        for turns in range(4):
            for angle in (-15,-.3,0,.3,15):
                full=Edit(dict(version=1,turns=turns,angle=angle,crop=None))
                w,h=full.extent
                edit=Edit(dict(version=1,turns=turns,angle=angle,crop=[30,40,w-60,h-80]))
                for source in ([320,240],[201.5,203.2],[422.8,310.6]):
                    result=point(edit.view_to_source,point(edit.source_to_view,source))
                    for a,b in zip(source,result):self.assertAlmostEqual(a,b,places=8)

    def test_letterboxing_cannot_expose_pixels_outside_crop(self):
        blob=reference();edit=Edit(dict(version=1,turns=0,angle=0,crop=[200,100,100,200]))
        rendered=Image.open(io.BytesIO(edit.render(blob)))
        self.assertEqual(rendered.getpixel((0,240)),(0,0,0))
        self.assertEqual(rendered.getpixel((320,240)),(255,255,255))
        self.assertFalse(edit.contains_source([100,100]))
        self.assertTrue(edit.contains_source([250,200]))
        self.assertFalse(edit.contains_source([10**400,0]))
        self.assertFalse(edit.contains_source([float('nan'),0]))

    def test_invalid_documents_rejected_before_render(self):
        for value in (None,[],{},dict(IDENTITY,extra=True),dict(IDENTITY,turns=True),
                      dict(IDENTITY,angle=10**400),dict(IDENTITY,angle=float('nan')),
                      dict(IDENTITY,crop=[0,0,641,480]),dict(IDENTITY,crop=[0,0,0,0]),
                      dict(IDENTITY,crop=[0,0,16.0,16])):
            if value is None:continue
            with self.subTest(value=str(value)[:80]):
                with self.assertRaises(ValueError):Edit(value)
        for raw in ('{"turns":0,"turns":1}','{"angle":NaN}',b'\xff'):
            with self.assertRaises(ValueError):strict_json(raw)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.store=Store(self.root);self.worker=Recognition(self.store)
        self.setup=Setup(self.root,Candidate,self.worker);self.ref=self.setup.add_reference(reference())
    def tearDown(self):self.temp.cleanup()
    def test_save_restart_noop_and_raw_reference_preservation(self):
        blob=self.setup.reference(self.ref)
        value=dict(version=1,turns=1,angle=0,crop=None)
        result=self.setup.save_image_edit(self.ref,value,None)
        before=(self.root/'image-edit.json').read_bytes()
        recreated=Setup(self.root,Candidate,Recognition(self.store))
        self.assertEqual(recreated.edits.status(),result)
        with patch.object(self.setup.edits,'atomic',side_effect=AssertionError('No repeated write')):
            self.assertEqual(self.setup.save_image_edit(self.ref,result['image_edit']['edit'],result['revision']),result)
        self.assertEqual((self.root/'image-edit.json').read_bytes(),before)
        self.assertEqual(self.setup.reference(self.ref),blob)
        self.assertEqual(self.store.status()['captures'],0)
    def test_hiding_marker_or_dial_does_not_replace_calibration(self):
        saved=self.setup.save(self.ref,DESIGN,None);before=self.setup.path.read_bytes()
        for crop in ([50,0,590,480],[0,0,300,480]):
            with self.assertRaisesRegex(ValueError,'image_crop_hides_marker'):
                self.setup.save_image_edit(self.ref,dict(IDENTITY,crop=crop),None)
        design=copy.deepcopy(DESIGN);design['markers']=[[50,50,20,20],[50,400,20,20],[50,200,20,20]]
        self.setup.save(self.ref,design,saved['revision'])
        with self.assertRaisesRegex(ValueError,'image_crop_hides_dial'):
            self.setup.save_image_edit(self.ref,dict(IDENTITY,crop=[0,0,100,480]),None)
        self.assertEqual(self.worker.reader.pipeline_id,Candidate(self.setup.status()['calibration']).pipeline_id)
        self.assertEqual(json.loads(before)['reference_sha256'],self.ref)
    def test_save_calibration_checks_current_crop(self):
        result=self.setup.save_image_edit(self.ref,dict(IDENTITY,crop=[0,0,300,480]),None)
        with self.assertRaisesRegex(ValueError,'image_crop_hides_marker'):self.setup.save(self.ref,DESIGN,None)
        self.assertIsNone(self.setup.active)
        self.assertEqual(self.setup.edits.status(),result)
    def test_calibration_unchanged_by_valid_rotation(self):
        saved=self.setup.save(self.ref,DESIGN,None);before=self.setup.path.read_bytes();pipeline=self.worker.reader.pipeline_id
        self.setup.save_image_edit(self.ref,dict(IDENTITY,turns=3,crop=None),None)
        self.assertEqual(self.setup.path.read_bytes(),before);self.assertEqual(self.worker.reader.pipeline_id,pipeline)
        self.assertEqual(self.setup.status()['revision'],saved['revision'])
    def test_conflict_external_edit_and_failed_write_preserve_active(self):
        result=self.setup.save_image_edit(self.ref,IDENTITY,None);path=self.root/'image-edit.json';before=path.read_bytes()
        with self.assertRaisesRegex(ValueError,'changed'):self.setup.save_image_edit(self.ref,dict(IDENTITY,turns=1,crop=None),None)
        with patch.object(self.setup.edits,'atomic',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.setup.save_image_edit(self.ref,dict(IDENTITY,turns=1,crop=None),result['revision'])
        self.assertEqual(path.read_bytes(),before);self.assertEqual(self.setup.edits.status(),result)
        path.write_bytes(b'changed externally')
        with self.assertRaisesRegex(ValueError,'changed'):self.setup.save_image_edit(self.ref,dict(IDENTITY,turns=2,crop=None),result['revision'])
        self.assertEqual(path.read_bytes(),b'changed externally')
    def test_corrupt_state_is_preserved_and_recovered_explicitly(self):
        path=self.root/'image-edit.json';path.write_bytes(b'broken')
        restarted=Setup(self.root,Candidate,Recognition(self.store));state=restarted.edits.status()
        self.assertEqual(state['recovery']['code'],'saved_image_edit_invalid')
        restarted.save_image_edit(self.ref,IDENTITY,state['revision'])
        self.assertEqual(next((self.root/'recovery').glob('image-edit-*.json')).read_bytes(),b'broken')
    def test_edit_conflict_during_preflight_cannot_commit_calibration(self):
        saved=self.setup.save(self.ref,DESIGN,None);before=self.setup.path.read_bytes()
        def interrupted(rgb):
            self.setup.save_image_edit(self.ref,dict(IDENTITY,turns=1,crop=None),None)
            return {'state':'estimated'}
        with patch.object(Candidate,'read_rgb',side_effect=interrupted):
            with self.assertRaisesRegex(ValueError,'image_edit_changed'):self.setup.save(self.ref,DESIGN,saved['revision'])
        self.assertEqual(self.setup.path.read_bytes(),before)


class HttpTests(unittest.TestCase):
    def setUp(self):
        PersistenceTests.setUp(self)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.store,False,None,setup=self.setup))
        self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
        self.origin='http://127.0.0.1:'+str(self.server.server_port)
        with urllib.request.urlopen(self.origin+'/api/setup') as response:self.token=json.load(response)['token']
    def tearDown(self):
        self.server.shutdown();self.thread.join();self.server.server_close();PersistenceTests.tearDown(self)
    def post(self,route,payload,token=True):
        headers={'Content-Type':'application/json'}
        if token:headers['X-AIEdge-Setup']=self.token
        raw=payload if isinstance(payload,bytes) else json.dumps(payload).encode()
        request=urllib.request.Request(self.origin+route,data=raw,headers=headers,method='POST')
        try:
            with urllib.request.urlopen(request) as response:return response.status,response.read(),response.headers
        except urllib.error.HTTPError as error:
            with error:return error.code,error.read(),error.headers
    def test_preview_hash_receipt_without_storage_or_capture(self):
        before={p.name:p.read_bytes() for p in self.root.glob('*') if p.is_file()}
        code,blob,headers=self.post('/api/setup/image-preview',dict(reference_sha256=self.ref,edit=dict(IDENTITY,turns=1,crop=None)))
        self.assertEqual(code,200);self.assertEqual(headers['Content-Type'],'image/png')
        self.assertEqual(headers['X-AIEdge-Source-SHA256'],self.ref)
        self.assertEqual(headers['X-AIEdge-Preview-SHA256'],hashlib.sha256(blob).hexdigest())
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.glob('*') if p.is_file()})
        self.assertEqual(self.store.status()['captures'],0)
    def test_auth_duplicate_keys_and_extra_fields_rejected(self):
        payload=dict(reference_sha256=self.ref,edit=IDENTITY)
        self.assertEqual(self.post('/api/setup/image-preview',payload,False)[0],403)
        self.assertEqual(self.post('/api/setup/image-preview',dict(payload,extra=True))[0],400)
        self.assertEqual(self.post('/api/setup/image-preview',b'{"reference_sha256":"a","reference_sha256":"b","edit":{}}')[0],400)
        self.assertEqual(self.post('/api/setup/image-edit',dict(payload,revision=None))[0],200)
        self.assertEqual(self.post('/api/setup/image-edit',dict(payload,edit=dict(IDENTITY,turns=2,crop=None),revision=None))[0],400)


if __name__=='__main__':unittest.main()
