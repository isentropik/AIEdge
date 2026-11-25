import json
import sqlite3
import threading
import unittest
from contextlib import ExitStack, closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import absolute_motion
import compact_capture
import original_meter
from capture import Store
from nominal_register import AbsolutePublisher
from reading_format import validate


class OriginalMeterTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store(tmp.name)
        self.checkpoint = Path(tmp.name) / 'meter.db'
        self.doc, self.fmt = validate(dict(version=1, pipeline_id='a'*64, unit='ft3',
            maximum_rate_per_second=.25, dials=[dict(index=0,value_per_revolution=1000,position_error=.01),
                                                dict(index=1,value_per_revolution=5,position_error=.02)]))
        self.now = datetime.now(timezone.utc)
        self.samples = {}
        self.source(1, 'old', '.00')
        self.source(2, 'new', '.02')
        self.source(3, 'new', '.20')
        self.source(4, 'new', '.30')
        with self.store.connect() as db:
            compact_capture.initialize(db)
            db.execute('CREATE TABLE consumption_segments(segment_id TEXT PRIMARY KEY,format_id TEXT,first_event INTEGER)')
            db.execute('INSERT INTO consumption_segments VALUES(?,?,2)', ('seg', self.fmt))
            db.execute('CREATE TABLE consumption_segment_links(first_event INTEGER,delta REAL)')
            db.execute('INSERT INTO consumption_segment_links VALUES(2,NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS capture_failure_boundaries(after_event_id INTEGER)')
        self.reader = SimpleNamespace(pipeline_id=self.doc['pipeline_id'], read_jpeg=self.read)
        self.rec = SimpleNamespace(reader=self.reader, lock=threading.Lock())
        stack = self.enterContext(ExitStack())
        for module in (absolute_motion, original_meter):
            stack.enter_context(patch.object(module, 'phases', self.phases))
        self.out = SimpleNamespace(config={'unique_id':'gas'}, base='gas', interval=10,
                                   daily=SimpleNamespace(store=self.store), _publish=lambda *args: None)
        self.pub = AbsolutePublisher(self.checkpoint)
        self.pub.originals = original_meter.OriginalMeter(self.store,self.rec)
        first = self.samples[1][0]
        track = absolute_motion.start(first, [(Decimal('100'), Decimal('100.01'))], 0)
        record = dict(state=None, absolute_motion=track, format_id=self.fmt,
                      source_identity=sha256(b'meter').hexdigest())
        with closing(sqlite3.connect(self.checkpoint)) as db, db:
            db.execute('CREATE TABLE nominal_register(identity TEXT PRIMARY KEY,record TEXT NOT NULL)')
            db.execute('INSERT INTO nominal_register VALUES(?,?)', ('gas',json.dumps(record)))

    def source(self, event, clock, pos):
        data = b'photo' + bytes([event])
        digest = sha256(data).hexdigest()
        src = dict(camera='meter', clock_id=clock, context_id='ctx', event_id=event, format_id=self.fmt,
            captured_at=(self.now-timedelta(seconds=(5-event)*10)).isoformat(), source_sha256=digest,
            monotonic_us=10000000*event)
        val = Decimal(pos)
        self.samples[event] = src, (val-Decimal('.01'), val+Decimal('.01'))
        with self.store.connect() as db:
            db.execute('INSERT INTO frames VALUES(?,?,?,?,?,?,0)',('meter',str(event),src['captured_at'],src['captured_at'],digest,len(data)))
            db.execute('INSERT INTO capture_events(camera,frame_id) VALUES(?,?)',('meter',str(event)))
            db.execute('INSERT INTO capture_clocks VALUES(?,?,?,?)',('meter',str(event),clock,src['monotonic_us']))
        (self.store.root/'images'/(digest+'.jpg')).write_bytes(data)

    def phases(self, db, first, last, doc, src, *, same_clock=True):
        return {i:v for i,v in self.samples.items() if first<=i<=last
                and (not same_clock or v[0]['clock_id']==src['clock_id'])}

    def read(self, data):
        return dict(state='estimated',source_sha256=sha256(data).hexdigest(),pipeline_id='a'*64,
                    dial_positions=[dict(state='estimated',position=1),dict(state='estimated',position=.04)])

    def receipt(self, event=2, frame=None):
        digest = self.samples[event][0]['source_sha256']
        with self.store.connect() as db:
            db.execute('INSERT INTO compact_exposures VALUES(?,?,?,?,?,?,?,?,?)',
                       (event,'b'*64,b'',digest,1,'a'*64,1,'{}',''))
            db.execute('INSERT INTO original_receipts VALUES(?,?,?,?,?,?,?)',
                       ('meter',event,frame or str(event),digest,6,'b'*64,event))

    def publish(self, event=4):
        src = self.samples[event][0]
        c = dict(event_observation=src,format_id=self.fmt,segment_id='seg',event_id=event,
                 source_sha256=src['source_sha256'],observation_context='ctx',observation_support={'partial':True})
        snap = dict(format=self.doc,consumption=c,_timing_event_id=event,_publication_segment_id='seg',
                    latest=dict(sha256=src['source_sha256'],captured_at=src['captured_at']))
        obs = {k:src[k] for k in ('captured_at','source_sha256','event_id','format_id')}
        self.pub.publish(self.out,obs,snap)
        return self.pub.displayed[1]

    def test_late_receipt_reanchors_then_replays_and_survives_restart(self):
        self.assertEqual(self.publish()['event_id'],1)
        self.receipt()
        display=self.publish()
        self.assertEqual((display['event_id'],display['anchor_event_id']),(4,2))
        self.assertEqual(Decimal(display['value_ft3']),Decimal('100.29'))
        self.assertEqual(display['source_sha256'],self.samples[4][0]['source_sha256'])
        self.pub = AbsolutePublisher(self.checkpoint)
        self.assertEqual(self.publish(),display)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT * FROM consumption_segment_links').fetchall(),[(2,None)])

    def test_wrong_frame_wrong_pipeline_and_expired_original_cannot_reanchor(self):
        self.receipt(frame='3')
        self.assertEqual(self.publish()['event_id'],1)
        with self.store.connect() as db:
            db.execute("UPDATE original_receipts SET frame='2'")
        self.reader.pipeline_id='c'*64
        self.assertEqual(self.publish()['event_id'],1)
        self.reader.pipeline_id='a'*64
        (self.store.root/'images'/(self.samples[2][0]['source_sha256']+'.jpg')).write_bytes(b'damaged')
        self.assertEqual(self.publish()['event_id'],1)

    def test_a_second_gap_or_missing_intermediate_phase_stops_replay(self):
        self.receipt()
        del self.samples[3]
        self.assertEqual(self.publish()['event_id'],2)
        with self.store.connect() as db:
            db.execute('INSERT INTO consumption_segment_links VALUES(4,NULL)')
        self.assertEqual(self.publish()['event_id'],2)

    def test_first_install_bootstraps_only_after_receipt(self):
        with closing(sqlite3.connect(self.checkpoint)) as db, db:
            db.execute('DELETE FROM nominal_register')
        self.pub.displayed=None
        self.receipt()
        self.assertEqual((self.publish()['anchor_event_id'],self.publish()['event_id']),(2,4))
