"""Supervised finite acquisition on a disposable ordinary capture ledger."""
import json
import tempfile
import time
import unittest
from datetime import datetime, timezone
from email.message import Message
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock
from bench_baseline import EXPECTED_BUNDLE, provision, prepare_trial
from bench_owner import service_owner
from bench_startup import gate, needs_camera_preflight
from capture import Store, Camera, Collector
from options import validate
from test_camera_image import CONFIG, CAPS


class Fixture:
    device = 'a'*32

    def __init__(self, interrupt=None):
        self.interrupt=interrupt
        self.generation=1
        self.current_owner=None
        self.owner=None
        self.starts=[]
        self.acks=[]
        self.batch=None
        self.epoch=time.time()-65

    def ticket(self):
        return f'{self.device}.{self.generation}'

    def status(self):
        owned=self.owner is not None and self.owner==self.current_owner
        return dict(boot=self.ticket(),started=bool(self.current_owner),owned=owned,
                    finished=bool(self.current_owner),attempted=5 if self.current_owner else 0,failed_mask=0)

    def start(self,state):
        assert self.batch==self.ticket() and self.current_owner is None
        self.starts.append(self.batch)
        if self.interrupt=='start':
            self.interrupt=None
            raise OSError('lost start')
        self.current_owner=self.owner

    def head(self):
        count=len(self.acks)
        if count==5*self.generation:return None
        data=b'\xff\xd8'+bytes([count])+b'\xff\xd9'
        headers=Message()
        fields={'X-AIEdge-Image-Orientation':'0','X-AIEdge-Burst-Slot':str(count%5),
                'X-AIEdge-Frame-Id':f'f{count}','X-AIEdge-SHA256':sha256(data).hexdigest(),
                'X-AIEdge-Clock-Id':'clock','X-AIEdge-Capture-Monotonic-Us':str(1+count*6000000),
                'X-AIEdge-Captured-At':datetime.fromtimestamp(self.epoch+count*6,timezone.utc).isoformat(),
                'Content-Type':'image/jpeg','Content-Length':str(len(data))}
        for k,v in fields.items():headers[k]=v
        return data,headers

    def ack(self,ident,digest):
        assert self.owner==self.current_owner and ident==f'f{len(self.acks)}'
        if self.interrupt=='ack':
            self.interrupt=None
            raise OSError('lost ack')
        self.acks.append(ident)

    def retire(self):
        assert len(self.acks)==self.generation*5
        self.generation+=1
        self.current_owner=None
        if self.interrupt=='retire':
            self.interrupt=None
            raise OSError('lost retirement receipt')
        return self.status()


class BufferedTrialTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.store=Store(self.root)
        # Use the schema installed by the actual consumption worker.
        import os
        from consumption import Consumption
        Consumption(self.store,Mock(observation_context=None),None,os.environ['AIEDGE_ACCOUNTING_LIBRARY'])
        self.ticket=Fixture.device+'.1'
        self.spec=self.ticket+'@'+sha256(CONFIG).hexdigest()

    def run_gate(self,camera):
        worker=Collector(self.store,Camera('http://localhost'),6)
        gate(worker,camera,self.root/'burst-bench.sqlite3',{},0,start_on_boot=self.ticket,count=2)

    def assert_completed(self,camera):
        self.assertEqual(camera.starts,[self.ticket,Fixture.device+'.2'])
        self.assertEqual(camera.acks,[f'f{i}' for i in range(10)])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT event_id FROM buffered_slot_events ORDER BY event_id').fetchall(),[(i,) for i in range(1,11)])
            self.assertEqual(db.execute('SELECT initial_boundary FROM buffered_batch_admissions ORDER BY after_event').fetchall(),[(1,),(0,)])
        self.assertFalse(needs_camera_preflight(self.root,self.store,''))
        self.assertFalse(needs_camera_preflight(self.root,self.store,self.spec))

    def test_retired_pair_can_return_to_ordinary_offline(self):
        provision(self.root,CONFIG,CAPS)
        cam=Fixture()
        self.run_gate(cam)
        self.assert_completed(cam)

    def test_lost_ack_can_reopen_without_duplicate(self):
        provision(self.root,CONFIG,CAPS)
        cam=Fixture('ack')
        with self.assertRaises(OSError):self.run_gate(cam)
        self.run_gate(cam)
        self.assert_completed(cam)

    def test_lost_retirement_observes_successor(self):
        provision(self.root,CONFIG,CAPS)
        cam=Fixture('retire')
        with self.assertRaises(OSError):self.run_gate(cam)
        self.run_gate(cam)
        self.assert_completed(cam)

    def test_uncertain_start_cannot_be_reissued(self):
        provision(self.root,CONFIG,CAPS)
        cam=Fixture('start')
        with self.assertRaises(OSError):self.run_gate(cam)
        with self.assertRaisesRegex(ValueError,'uncertain start'):self.run_gate(cam)
        self.assertEqual(cam.starts,[self.ticket])
        self.assertTrue(needs_camera_preflight(self.root,self.store,''))

    def test_unactivated_service_accepts_old_camera(self):
        self.assertFalse(needs_camera_preflight(self.root,self.store,''))
        provision(self.root,CONFIG,CAPS)
        self.assertFalse(needs_camera_preflight(self.root,self.store,''))

    def test_unverified_firmware_cannot_provision(self):
        c=Collector(self.store,Camera('http://localhost'),6)
        image=Mock()
        image.request.return_value={'running_bundle_id':EXPECTED_BUNDLE,'running_bundle_verified':False,'active':False}
        with self.assertRaisesRegex(ValueError,'firmware'):prepare_trial(self.spec,c,image,self.root)
        self.assertFalse((self.root/'burst-bench.sqlite3').exists())
        self.assertEqual(image.request.call_count,1)

    def test_activation_requires_fixed_cadence_and_event_mode(self):
        self.assertEqual(validate({})['buffered_trial'],'')
        with self.assertRaises(ValueError):validate({'buffered_trial':self.spec})
