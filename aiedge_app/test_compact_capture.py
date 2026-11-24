"""Admission, recognition, restart, and chunk receipts share the actual release paths."""
from email.message import Message
from io import BytesIO
from types import SimpleNamespace
import json
import struct
import time
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
import compact_capture as q
from capture import Camera,Store
from event_recognition import EventRecognition
from test_event_recognition import FakeReader,DOC,CONFIG,CAPS


def jpeg(image):
    dst=BytesIO()
    image.save(dst,format='JPEG',quality=25)
    return dst.getvalue()


DOCUMENT = {'image_size':[640,480],'dials':[{}, {}, {'crop':[74,46,81,60]}],
            'markers':[{'box':[19,30,12,11]}, {'box':[588,463,49,16]}, {'box':[1,0,12,14]}]}
PROFILE = q.digest(b'synthetic calibration')
BOXES = [[66,38,163,114], [3,14,47,57], [572,447,640,480], [0,0,29,30]]


def packet(tick=1000, profile=PROFILE, boxes=BOXES):
    im=Image.new('RGB',(640,480),(112,109,90))
    original=jpeg(im)
    pieces=[jpeg(im.crop(box)) for box in boxes]
    clock='a'*32
    meta=dict(version=1,profile=profile,sequence=tick,clock=clock,monotonic_us=tick,
              frame_id=f'{clock}-{tick:x}',captured_at='2026-10-02T12:00:00.000000Z',mode='fine',
              source_sha256=q.digest(original),source_bytes=len(original),
              parts=[dict(size=len(data),box=list(box),sha256=q.digest(data)) for box,data in zip(boxes,pieces)])
    header=json.dumps(meta,separators=(',',':')).encode()
    return struct.pack('>I',len(header))+header+b''.join(pieces),original


def headers(values):
    msg=Message()
    for k,v in values.items():msg[k]=str(v)
    return msg


class Reader(FakeReader):
    profile=PROFILE
    runtime=SimpleNamespace(document=DOCUMENT)
    def read_rgb(self,data,observed):
        return self.read_jpeg(data,observed)


class CompactTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name)
        self.reader=Reader()
        self.rec=EventRecognition(self.store,self.reader,DOC,CONFIG,CAPS)
        self.camera=Camera('http://localhost')
        self.worker=q.CompactCapture(self.store,self.camera,self.rec)
        self.data,self.image=packet()

    def collect(self,anchor='0',data=None):
        data=self.data if data is None else data
        response=headers({'Content-Type':'application/x-aiedge-q25','X-AIEdge-Anchor':anchor,
                          'X-AIEdge-SHA256':q.digest(data)})
        with patch.object(q,'request',return_value=(response,data)):
            return self.worker.collect(time.monotonic())

    def test_only_fine_is_observed_and_history_replays_after_restart(self):
        self.assertTrue(self.collect('deferred'))
        self.assertTrue(self.worker.force_anchor)
        self.assertTrue(self.rec.once())
        source=q.digest(self.image)
        result=self.rec.stored_event(1,source,self.reader.pipeline_id)
        self.assertEqual(result['decision']['requested_mode'],'FINE')
        self.assertEqual(result['result']['observation_support']['observed'],[False,False,True])
        self.assertFalse(self.collect('deferred'))
        resumed=EventRecognition(self.store,self.reader,DOC,CONFIG,CAPS)
        self.assertEqual(resumed.observation_context,self.rec.observation_context)
        self.assertEqual(resumed.latest()['event_observation']['event_id'],1)
        self.assertEqual(self.store.status()['captures'],1)
        self.assertEqual(self.store.history()['items'][0]['compact_preview'],'fine_dial')
        with Image.open(BytesIO(q.preview(self.store,'1'))) as im:self.assertEqual(im.size,(97,76))
        with self.assertRaises(FileNotFoundError):self.store.image(source)

    def test_corrupt_compact_cannot_enter_capture_history(self):
        self.worker.force_anchor=False
        wrong=self.data[:-1]+bytes([self.data[-1]^1])
        with self.assertRaisesRegex(ValueError,'compact_part_integrity'):self.collect(data=wrong)
        self.assertEqual(self.store.status()['captures'],0)
        self.assertFalse(self.worker.available({'state':'ready'}))
        self.reader.profile='other'
        self.assertFalse(self.worker.available({'state':'ready','q25':True}))

    def test_camera_must_advertise_matching_calibration_before_any_compact_request(self):
        from camera_status import validate
        from test_camera_status import READY
        for advertised in (None, False, 'bad', 'e'*64, PROFILE):
            ready = validate({**READY, 'q25':True, 'q25_profile':advertised})
            self.assertEqual(self.worker.available(ready), advertised == PROFILE)

    def test_wrong_dial_mapping_uses_full_photos(self):
        self.assertFalse(self.worker.available({'q25':True}))
        self.assertFalse(self.worker.available({'q25':True, 'q25_profile':'f'*64}))
        self.assertTrue(self.worker.available({'q25':True,'q25_profile':PROFILE}))
        self.rec.document={**self.rec.document,'dials':list(reversed(self.rec.document['dials']))}
        self.assertFalse(self.worker.available({'q25':True,'q25_profile':PROFILE}))

    def test_receive_binds_profile_and_all_regions_to_saved_calibration(self):
        for data, reason in [(packet(profile='d'*64)[0],'compact_calibration_changed'),
                             (packet(boxes=[BOXES[0],BOXES[2],BOXES[1],BOXES[3]])[0],'compact_geometry')]:
            with self.assertRaisesRegex(ValueError,reason):
                self.collect('1',data)
        self.assertEqual(self.store.status()['captures'],0)

    def test_other_exposure_cannot_satisfy_original_receipt(self):
        self.collect('1')
        seq,source,frame=9,q.digest(self.image),'a'*32+'-3e8'
        with self.assertRaisesRegex(ValueError,'original_exposure_conflict'):
            self.worker._receipt((seq,source,len(self.image),self.image,frame,'b'*64),time.monotonic()+2)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM original_receipts').fetchone(),(0,))
        with self.assertRaises(FileNotFoundError):self.store.image(source)

    def test_restart_mid_original_and_ack_loss(self):
        self.collect('1')
        self.assertFalse(self.rec.once())  # Native fine observation is already committed.
        source=q.digest(self.image); state={'acked':False,'posts':0}
        def fetch(camera,path,**kw):
            if path.endswith('/ack'):
                self.assertEqual(kw['body'],f'9 {source} 0'.encode())
                state['acked']=True;state['posts']+=1
                raise TimeoutError('ACK response lost')
            if state['acked']:return None,None
            offset=int(kw['headers']['X-AIEdge-Offset'])
            body=self.image[offset:offset+1024]
            return headers({'X-AIEdge-Size':len(self.image),'X-AIEdge-Sequence':9,'X-AIEdge-Original':source,
                            'X-AIEdge-Frame-Id':'a'*32+'-3e8','X-AIEdge-Proof':q.digest(self.data),'X-AIEdge-Offset':offset,'X-AIEdge-SHA256':q.digest(body)}),body
        with patch.object(q,'request',side_effect=fetch):
            self.assertTrue(self.worker.download(time.monotonic()+2))
            other=q.CompactCapture(self.store,self.camera,self.rec)
            with self.store.connect() as db:self.assertEqual(db.execute('SELECT length(body) FROM original_download').fetchone(),(1024,))
            for _ in range((len(self.image)-1)//1024):other.download(time.monotonic()+2)
            with self.assertRaises(TimeoutError):other.download(time.monotonic()+2)
            self.assertEqual(self.store.image(source),self.image)
            other.download(time.monotonic()+2)
            self.assertEqual(state['posts'],1)
        self.assertTrue(self.rec.once())
        self.assertEqual(self.rec.stored_event(1,source,self.reader.pipeline_id)['decision']['requested_mode'],'FULL')

