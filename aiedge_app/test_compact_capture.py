"""Admission, recognition, restart, and chunk receipts share the actual release paths."""
from email.message import Message
from io import BytesIO
from types import SimpleNamespace
import json
import struct
import threading
import time
import unittest
import urllib.error
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

    def collect(self,anchor='0',data=None,**options):
        data=self.data if data is None else data
        response=headers({'Content-Type':'application/x-aiedge-q25','X-AIEdge-Anchor':anchor,
                          'X-AIEdge-SHA256':q.digest(data)})
        with patch.object(q,'request',return_value=(response,data)):
            return self.worker.collect(time.monotonic(),**options)

    def test_slow_capture_reserves_link_without_forgetting_originals(self):
        for previous,slow_probe,expect_overlap in ((0,True,False),(5.1,False,False),(1,False,True)):
            self.worker.original_pending=True
            self.worker.previous_exchange_seconds=previous
            phases={}
            with patch.object(self.worker,'_while_settling') as original:
                self.collect('1',reserve_link=slow_probe,interval=10,phases=phases)
                self.assertEqual(original.called,expect_overlap)
                self.assertEqual(phases['concurrent_original_worker'],expect_overlap)
                self.assertTrue(self.worker.original_pending)

    def test_capture_timing_identifies_exposure_and_retained_original(self):
        fields={}
        self.assertTrue(self.collect('1',phases=fields))
        with self.store.connect() as db:
            saved=db.execute('SELECT e.event_id,f.captured_at FROM capture_events e JOIN frames f USING(camera,frame_id)').fetchone()
        self.assertEqual((fields['event_id'],fields['exposure_utc']),saved)
        self.assertTrue(fields['original_retained'])

    def test_idle_checks_empty_queue_again_on_anchor_restart_or_deadline(self):
        stop=threading.Event()
        with patch('compact_capture.time.monotonic',return_value=100),patch.object(self.worker,'download',return_value=False) as download:
            self.worker.idle(stop,110)
            self.worker.idle(stop,110)
            self.assertEqual(download.call_count,1)
            self.collect('1')
            self.worker.idle(stop,110)
            self.assertEqual(download.call_count,2)
            with patch('compact_capture.time.monotonic',return_value=161):
                self.worker.idle(stop,171)
                self.assertEqual(download.call_count,3)
            restarted=q.CompactCapture(self.store,self.camera,self.rec)
            with patch.object(restarted,'download',return_value=False) as discover:
                restarted.idle(stop,110)
                discover.assert_called_once()

    def test_either_worker_clears_failure_on_empty_or_progress(self):
        for worker in ('idle','settling'):
            for progress in (False,True):
                with self.subTest(worker=worker,progress=progress):
                    stop=threading.Event()
                    self.worker.original_pending=True
                    self.worker.download_issue={'error':'TimeoutError'}
                    def advance(deadline):
                        stop.set()
                        return progress
                    with patch.object(self.worker,'download',side_effect=advance) as download:
                        if worker=='idle':
                            self.worker.idle(stop,time.monotonic()+3)
                        else:
                            self.worker._while_settling(stop,time.monotonic())
                    download.assert_called_once()
                    self.assertIsNone(self.worker.download_error)
                    self.assertEqual(self.worker.original_pending,progress)

    def test_request_failures_record_phase_identity_and_byte_offset(self):
        src=q.digest(self.image)
        row=(9,src,len(self.image),self.image[:1024],'a'*32+'-3e8',q.digest(self.data))
        with self.store.connect() as db:
            db.execute('INSERT INTO original_download VALUES(?,?,?,?,?,?,?)',(self.camera.origin,*row))
        def fail(camera,path,**kw):
            self.assertEqual(path,'/api/v1/original')
            self.assertEqual(kw['headers']['X-AIEdge-Offset'],'1024')
            kw['timing'].update(connected_at=1,headers_at=2)
            raise TimeoutError()
        with patch.object(q,'request',side_effect=fail),patch('lifecycle.lifecycle_event') as journal:
            self.worker.idle(threading.Event(),time.monotonic()+3)
        issue=self.worker.download_issue
        self.assertEqual((issue['operation'],issue['offset'],issue['sequence'],issue['frame_id']),
                         ('jpeg',1024,9,row[4]))
        self.assertEqual((issue['phase'],issue['cause'],issue['worker']),('response_body','TimeoutError','idle'))
        journal.assert_called_once_with('original_download_failure',**issue)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT length(body) FROM original_download').fetchone(),(1024,))

    def test_unknown_queue_head_and_wrapped_connect_timeout(self):
        with patch.object(q,'request',side_effect=urllib.error.URLError(TimeoutError())),patch('lifecycle.lifecycle_event',side_effect=BrokenPipeError):
            self.worker._while_settling(threading.Event(),time.monotonic())
        issue=self.worker.download_issue
        self.assertEqual((issue['error'],issue['cause'],issue['phase']),('URLError','TimeoutError','connect'))
        self.assertEqual((issue['operation'],issue['sequence'],issue['offset']),('queue_head',None,0))
        self.assertEqual(issue['worker'],'settling')

    def test_expired_original_window_never_dispatches_or_reports_a_network_timeout(self):
        with patch.object(self.camera.opener,'open') as opened,patch('lifecycle.lifecycle_event') as journal:
            with self.assertRaises(q.OriginalWindowEnded):
                self.worker.download(time.monotonic()-1)
            for worker in ('settling','idle'):
                with patch.object(self.worker,'download',side_effect=q.OriginalWindowEnded):
                    if worker=='settling':self.worker._while_settling(threading.Event(),time.monotonic())
                    else:self.worker.idle(threading.Event(),time.monotonic()+3)
            opened.assert_not_called()
            journal.assert_not_called()
            self.assertIsNone(self.worker.download_issue)

    def test_deferred_anchor_keeps_original_drain_available_on_a_slow_link(self):
        self.collect('deferred')
        self.assertTrue(self.worker.original_pending)
        with patch.object(self.worker,'_while_settling') as drain:
            self.collect('1',reserve_link=True,interval=10)
            drain.assert_called_once()

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

    def test_ack_yields_before_post_and_rechecks_uncertain_post_or_restart(self):
        self.collect('1')
        source=q.digest(self.image)
        frame='a'*32+'-3e8'
        proof=q.digest(self.data)
        row=(9,source,len(self.image),self.image,frame,proof)
        with self.store.connect() as db:
            db.execute('INSERT INTO original_download VALUES(?,?,?,?,?,?,?)',(self.camera.origin,*row))
        head=headers({'X-AIEdge-Sequence':9,'X-AIEdge-Original':source,'X-AIEdge-Frame-Id':frame,'X-AIEdge-Proof':proof})
        real_request=q.request
        calls=[]
        def fetch(camera,path,**kw):
            if path.endswith('/ack'):
                return real_request(camera,path,**kw)
            calls.append('head')
            return head,b'x'
        with patch.object(q,'request',side_effect=fetch),patch.object(self.camera.opener,'open',side_effect=TimeoutError) as opened:
            with self.assertRaises(q.OriginalWindowEnded):
                self.worker.download(time.monotonic()+.745)
            opened.assert_not_called()
            self.assertEqual(self.store.image(source),self.image)
            self.assertEqual(calls,['head'])
            # A process restart must obtain a fresh full identity check.
            other=q.CompactCapture(self.store,self.camera,self.rec)
            with self.assertRaises(q.OriginalWindowEnded):
                other.download(time.monotonic()+.745)
            self.assertEqual(calls,['head','head'])
            with self.assertRaises(TimeoutError) as failure:
                other.download(time.monotonic()+1.5)
            self.assertNotIsInstance(failure.exception,q.OriginalWindowEnded)
            opened.assert_called_once()
            self.assertEqual(calls,['head','head'])
            # The timeout used up the confirmation. Identity changed at the head.
            head.replace_header('X-AIEdge-Proof','b'*64)
            with self.assertRaisesRegex(ValueError,'original_head_identity_changed'):
                other.download(time.monotonic()+1.5)
            opened.assert_called_once()
            self.assertEqual(calls,['head','head','head'])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT sequence FROM original_download').fetchall(),[(9,)])

    def test_short_idle_step_can_use_remaining_slack_but_never_the_next_capture(self):
        for due,expected in ((105,[101.5,102.255]),(102,[101.5])):
            clock=[100.0]
            deadlines=[]
            def advance(deadline):
                deadlines.append(deadline)
                if len(deadlines)==1:
                    clock[0]+=.755
                    self.worker.confirmed_ack_head=(9,)
                    raise q.OriginalWindowEnded()
                return False
            with patch.object(q.time,'monotonic',side_effect=lambda:clock[0]),patch.object(self.worker,'_advance_original',side_effect=advance):
                self.worker.idle(threading.Event(),due)
            self.assertEqual(len(deadlines),len(expected))
            for actual,want in zip(deadlines,expected):
                self.assertAlmostEqual(actual,want)

    def test_ack_head_change_while_deferred_does_not_remove_new_photo(self):
        self.collect('1')
        src=q.digest(self.image);frame='a'*32+'-3e8';proof=q.digest(self.data)
        row=(9,src,len(self.image),self.image,frame,proof)
        with self.store.connect() as db:
            db.execute('INSERT INTO original_download VALUES(?,?,?,?,?,?,?)',(self.camera.origin,*row))
        first=headers({'X-AIEdge-Sequence':9,'X-AIEdge-Original':src,'X-AIEdge-Frame-Id':frame,'X-AIEdge-Proof':proof})
        conflict=urllib.error.HTTPError(self.camera.origin,409,'wrong queue head',{},None)
        with patch.object(self.worker,'_original_request',side_effect=[
            (first,b'x'),q.OriginalWindowEnded(),conflict,(headers({'X-AIEdge-Sequence':10}),b'y')
        ]) as request,patch('lifecycle.lifecycle_event') as journal:
            with self.assertRaises(q.OriginalWindowEnded):self.worker.download(time.monotonic()+.745)
            with self.assertRaises(urllib.error.HTTPError):self.worker.download(time.monotonic()+2)
            self.worker.download(time.monotonic()+2)
            self.assertEqual([c.args[0] for c in request.call_args_list],['receipt_head','ack','ack','receipt_head'])
            self.assertEqual(request.call_args_list[2].kwargs['body'],f'9 {src} 0'.encode())
            self.assertEqual(journal.call_args.args,('original_ack_resolution',))
            self.assertEqual(journal.call_args.kwargs['outcome'],'queue_head_changed_before_post')
            self.assertEqual(journal.call_args.kwargs['observed_sequence'],10)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT seq FROM original_receipts').fetchall(),[(9,)])
            self.assertIsNone(db.execute('SELECT 1 FROM original_download').fetchone())

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
            with patch('lifecycle.lifecycle_event') as journal:
                other.idle(threading.Event(),time.monotonic()+3)
            issue=other.download_issue
            self.assertEqual((issue['operation'],issue['path'],issue['method'],issue['sequence']),
                             ('ack','/api/v1/original/ack','POST',9))
            journal.assert_called_once_with('original_download_failure',**issue)
            self.assertEqual(self.store.image(source),self.image)
            other._while_settling(threading.Event(),time.monotonic())
            self.assertIsNone(other.download_error)
            self.assertEqual(state['posts'],1)
        self.assertTrue(self.rec.once())
        self.assertEqual(self.rec.stored_event(1,source,self.reader.pipeline_id)['decision']['requested_mode'],'FULL')

