from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import sqlite3
import unittest
from unittest.mock import patch

from meter_history import millis
from reading_format import validate
from tracked_bounds import TrackedBounds, cents


class TrackedBoundsTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE capture_events(event_id INTEGER PRIMARY KEY, camera, frame_id);
            CREATE TABLE frames(camera, frame_id, captured_at, sha256);
            CREATE TABLE capture_failure_boundaries(after_event_id);
            CREATE TABLE consumption_segment_links(first_event);
            CREATE TABLE continuous_capture_attempts(attempt_id,first_event,after_event_id,started_at);
            CREATE TABLE continuous_capture_outcomes(attempt_id,outcome,event_id,error,finished_at);
        """)
        self.doc, self.rev = validate(dict(version=1,pipeline_id='a'*64,unit='ft3',maximum_rate_per_second=1,
                                           dials=[dict(index=0,value_per_revolution=5,position_error=.1)]))
        self.policy = dict(format_id=self.rev,pipeline_id='a'*64,capacity_cfh=720)
        self.opening = datetime(2026,1,1,10,tzinfo=timezone.utc)
        self.samples = {}
        self.points = []
        self.calc = TrackedBounds(self)
        def read(db, lo, hi, doc, source, same_clock=True):
            return {e:v for e,v in self.samples.items() if lo <= e <= hi and
                    all(v[0][k]==source[k] for k in ('camera','format_id'))}
        for name in ('tracked_bounds.phases', 'optical_daily.phases'):
            patched=patch(name,read)
            patched.start()
            self.addCleanup(patched.stop)

    @contextmanager
    def connect(self):
        yield self.db

    def frame(self, eid, offset, ticks, position, nominal, group=0):
        at=self.opening+timedelta(seconds=offset)
        src=dict(event_id=eid,camera='meter',format_id=self.rev,context_id='ctx',clock_id='boot',
                 monotonic_us=ticks,captured_at=at.isoformat(),source_sha256=f'{eid:064x}')
        self.db.execute('INSERT INTO capture_events VALUES(?,?,?)',(eid,'meter',eid))
        self.db.execute('INSERT INTO frames VALUES(?,?,?,?)',('meter',eid,at.isoformat(),src['source_sha256']))
        self.db.execute('INSERT INTO continuous_capture_attempts VALUES(?,?,?,?)',
                        (eid,1,eid-1,(at-timedelta(seconds=1)).isoformat()))
        self.db.execute('INSERT INTO continuous_capture_outcomes VALUES(?,?,?,?,?)',
                        (eid,'committed',eid,None,(at+timedelta(seconds=1)).isoformat()))
        pos=Decimal(position)
        self.samples[eid]=src,(pos-Decimal('.05'),pos+Decimal('.05'))
        self.points.append([millis(at),nominal,eid,group])

    def get(self, gaps=(), policy=None):
        first, last=self.points[0],self.points[-1]
        origin=self.opening.isoformat()
        ms=millis(self.opening.replace(hour=0))
        track=dict(midnight=ms,format=self.rev,points=self.points,dial_from=[first[2],first[0]],
                   dial_gaps=[[ms,first[0]],*gaps])
        state=dict(day='2026-01-01',timezone='UTC',coverage_started_at=origin,method='nominal_meter_movement_v1',
                   measured_at=self.samples[last[2]][0]['captured_at'],
                   source_sha256=f'{last[2]:064x}',value_ft3=last[1],event_id=last[2])
        return self.calc.snapshot(dict(daily_nominal=state,movement_history=track),self.doc,
                                  self.policy if policy is None else policy)

    def test_clock_only_requires_both_commits_and_a_unique_overlapping_winding(self):
        self.frame(1,0,0,'1',0)
        self.frame(2,16,15500000,'1.001',0,1)
        gap=[p[0] for p in self.points]
        saved=self.get([gap])
        self.assertEqual(saved['joins'],[gap])
        self.assertEqual(saved['edges'][0]['use'],[0,11])
        self.assertEqual(self.get([gap],dict(self.policy,pipeline_id='b'*64))['joins'],[])
        self.db.execute('INSERT INTO capture_failure_boundaries VALUES(1)')
        blocked=self.get([gap])
        self.assertEqual(blocked['joins'],[])
        self.assertEqual(blocked['edges'][0]['use'],[0,0])
        self.db.execute('DELETE FROM capture_failure_boundaries')
        self.db.execute('UPDATE continuous_capture_outcomes SET outcome="unknown" WHERE event_id=2')
        self.assertEqual(self.get([gap])['joins'],[])

    def test_missing_phases_break_the_range_but_later_measurements_support_an_interval(self):
        for i,pos in enumerate(['1','1.2','1.4','1.6','1.8'],1):
            self.frame(i,(i-1)*4,(i-1)*4000000,pos,(i-1)*.2)
        del self.samples[3]
        edges=self.get()['edges']
        self.assertEqual([(e['start'][0],e['end'][0]) for e in edges],[(1,2),(4,5)])
        self.assertIsNone(edges[-1]['total'])
        self.assertEqual(edges[-1]['use'],[10,30])
        self.assertEqual(cents((Decimal('.10999'),Decimal('.30001'))),[10,31])

    def test_incomplete_hour_ends_at_the_last_reproducible_nominal(self):
        for i,position in enumerate(['1','1.2','1.4','1.6'],1):
            self.frame(i,4*(i-1),4000000*(i-1),position,0 if i==1 else .2*(i-1)-.1)
        self.points=[self.points[0],self.points[-1]]
        del self.samples[3]
        [edge]=self.get()['edges']
        self.assertEqual(edge['end'][0],2)
        self.assertEqual(edge['point'],[edge['end'][1],.1,2,0])
        self.assertEqual(edge['until'],[4,self.points[-1][0]])
        self.assertEqual((edge['use'],edge['total']),([10,30],[10,30]))

    def test_changed_epoch_and_segment_boundaries_are_never_joined(self):
        self.frame(1,0,0,'1',0)
        self.frame(2,6,6100000,'1.001',0,1)
        gap=[p[0] for p in self.points]
        self.samples[2][0]['clock_id']='other'
        self.assertEqual(self.get([gap])['joins'],[])
        self.samples[2][0].update(clock_id='boot',monotonic_us=6500000)
        self.db.execute('INSERT INTO consumption_segment_links VALUES(2)')
        self.assertEqual(self.get([gap])['joins'],[])
