"""Daily movement must survive coarse-register revisions without inventing a turn."""
import json
import sqlite3
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from nominal_motion import recover, step

DOCUMENT = dict(pipeline_id='p', maximum_rate_per_second=0.5, dials=[
    dict(index=0, value_per_revolution=10000, position_error=0.1),
    dict(index=1, value_per_revolution=5, position_error=0.1)])


class SavedMotionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE capture_events(event_id INTEGER PRIMARY KEY,camera,frame_id);
            CREATE TABLE frames(camera,frame_id,captured_at,sha256);
            CREATE TABLE capture_clocks(camera,frame_id,clock_id,monotonic_us);
            CREATE TABLE consumption_records(segment_id,event_id,result, PRIMARY KEY(segment_id,event_id));
            CREATE TABLE consumption_segment_links(segment_id,prior_segment_id,first_event);
            CREATE TABLE capture_failure_boundaries(after_event_id);
        """)
        self.midnight = datetime(2026,11,21,tzinfo=timezone.utc)
        self.rows = {}
        self.prior = None

    @contextmanager
    def connect(self):
        yield self.db

    def add(self, eid, limits, *, observed=True, seconds=None, segment='a', camera='meter', clock='clock'):
        digest = format(eid,'064x')
        seconds = eid*10 if seconds is None else seconds
        stamp = (self.midnight+timedelta(seconds=seconds)).isoformat()
        src = dict(event_id=eid, camera=camera, captured_at=stamp, clock_id=clock,
                   monotonic_us=seconds*1000000, source_sha256=digest, format_id='f',context_id='context')
        rec = dict(event_id=eid,format_id='f',source_sha256=digest,segment_id=segment,
                   observation_accepted=True,observation_context='context',observation_current_through_us=src['monotonic_us'],
                   through_captured_at=stamp,event_observation=src,
                   observation_support=dict(source_sha256=digest,pipeline_id='p',document_observed=[True,observed]),
                   absolute=dict(unit='ft3',provenance='temporal_consumption_bounds',
                                 bounds=dict(state='bounded',wraps_register=False,ranges=[
                                     dict(lower=a,upper=b) for a,b in limits])))
        self.rows[eid] = rec
        self.db.execute('INSERT INTO capture_events VALUES(?,?,?)',(eid,camera,eid))
        self.db.execute('INSERT INTO frames VALUES(?,?,?,?)',(camera,eid,stamp,digest))
        self.db.execute('INSERT INTO capture_clocks VALUES(?,?,?,?)',(camera,eid,clock,src['monotonic_us']))
        self.db.execute('INSERT INTO consumption_records VALUES(?,?,?)',(segment,eid,json.dumps(rec)))
        return rec

    def replay(self,eid, full=None):
        rec = self.rows[eid]
        obs = dict(rec['event_observation'], segment_id=rec['segment_id'])
        return recover(self.prior,obs,full,datetime.fromisoformat(obs['captured_at']).date(),
                       'UTC',self,dict(consumption=rec,format=DOCUMENT))

    def anchor(self):
        self.add(1,[(100,100.1),(105,105.1)])
        self.prior = self.replay(1)
        self.assertEqual(self.prior['state']['value_ft3'],'0.00')

    def test_old_branch_disappears_and_duplicate_is_idempotent(self):
        self.anchor()
        self.add(2,[(105,105.1)])
        self.assertEqual(self.replay(2)['state']['value_ft3'],'0.00')
        self.add(3,[(105.3,105.4)])
        record = self.replay(3)
        self.assertEqual(record['state']['value_ft3'],'0.20')
        self.prior = json.loads(json.dumps(record))
        self.assertEqual(self.replay(3),self.prior)
        self.assertIsNone(self.replay(2))
        self.rows[3]['event_observation']['source_sha256']='f'*64
        self.assertIsNone(self.replay(3))

    def test_wrap_only_counts_supported_fraction(self):
        self.add(1,[(104.85,104.95)])
        self.prior = self.replay(1)
        self.add(2,[(110.2,110.3)])
        self.assertEqual(self.replay(2)['state']['value_ft3'],'0.25')
        self.add(3,[(110.2,110.3)])
        self.assertEqual(self.replay(3)['state']['value_ft3'],'0.25')

    def test_missing_observation_clock_change_and_failure_never_bridge(self):
        for eid,opts in [(1,{}),(2,dict(observed=False)),(3,{}),(4,dict(clock='new')),(5,dict(clock='new'))]:
            self.add(eid,[(100+eid,100.1+eid)],**opts)
        self.prior = self.replay(1)
        self.db.execute('INSERT INTO capture_failure_boundaries VALUES(4)')
        state = self.replay(5)
        self.assertEqual(state['state']['value_ft3'],'0.00')
        self.assertEqual(state['state']['status'],'partial_coverage')
        self.assertEqual(state['movement']['group'],3)
        self.assertTrue(state['movement']['dial_gaps'])

    def test_impossible_rate_reanchors_without_charging(self):
        self.anchor()
        self.add(2,[(102,102.1)],seconds=11)
        self.assertEqual(self.replay(2)['state']['value_ft3'],'0.00')
        self.add(3,[(102.5,102.6)],seconds=15)
        self.assertEqual(self.replay(3)['state']['value_ft3'],'0.40')

    def test_wrong_source_and_corrupt_endpoint_do_not_advance(self):
        self.anchor()
        self.add(2,[(100.6,100.7)],camera='other')
        self.assertIsNone(self.replay(2))
        self.rows[2]['event_observation']['clock_id']='different'
        self.assertIsNone(self.replay(2))

    def test_late_start_and_midnight_never_attribute_previous_day(self):
        self.anchor()
        self.add(2,[(101.0,101.1)],seconds=86408)
        self.add(3,[(101.3,101.4)],seconds=86418)
        src = self.rows[2]['event_observation']
        full = dict(after=src,day='2026-11-22',timezone='UTC')
        result = self.replay(3,full)
        self.assertEqual(result['state']['day'],'2026-11-22')
        self.assertEqual(result['state']['value_ft3'],'0.20')
        self.assertEqual(result['movement']['points'][0][2],2)
        self.assertEqual(self.replay(3)['state']['value_ft3'],'0.00')

    def test_pages_complete_and_do_not_skip_an_unobserved_tail(self):
        self.anchor()
        for eid in range(2,272):
            self.add(eid,[(100,100.1)],observed=not 255<=eid<=261)
        self.prior = self.replay(271)
        self.assertEqual(self.prior['state']['event_id'],254)
        self.assertEqual(self.prior['movement']['dial_cursor'],257)
        self.prior = json.loads(json.dumps(self.prior))
        self.assertIsNone(self.replay(255))
        result = self.replay(271)
        self.assertEqual(result['state']['event_id'],271)
        self.assertEqual(result['movement']['group'],1)

    def test_no_optional_turn_or_negative_increment(self):
        fine = Decimal(5)
        self.assertEqual(step(('2','2.1'),(Decimal(2),Decimal('2.1')),fine,100),
                         (Decimal(2),Decimal('2.1')))
        self.assertIsNone(step(('2','2.1'),(Decimal(1),Decimal('1.1')),fine,Decimal('.5')))

    def test_long_silence_and_backdated_frame_exclude_their_delta(self):
        self.anchor()
        self.add(2,[(103,103.1)],seconds=670)
        self.add(3,[(104,104.1)],seconds=669)
        self.add(4,[(104,104.1)],seconds=685)
        result = self.replay(4)
        self.assertEqual(result['state']['value_ft3'],'0.00')
        self.assertEqual(result['movement']['group'],2)
        self.assertEqual(result['state']['event_id'],4)

    def test_tighter_or_wider_bounds_cannot_move_a_stationary_dial(self):
        self.anchor()
        for eid,high in [(2,'70.00'),(3,'10.00')]:
            rec = self.add(eid,[(105,105.1)])
            full = dict(day='2026-11-21',timezone='UTC',through=rec['event_observation'],
                        lower='0.00',upper=high,low_use_estimate={'value_ft3':'0.00'})
            self.prior = self.replay(eid,full)
            state = self.prior['state']
            self.assertEqual((state['value_ft3'],state['upper_ft3'],state['bounds_event_id']),('0.00',float(high),eid))

    def test_empty_page_resumes_without_inventing_an_opening_measurement(self):
        for eid in range(1,265):
            self.add(eid,[(102,102.1)],observed=eid>=260)
        bracket = dict(day='2026-11-21',timezone='UTC',after=self.rows[1]['event_observation'])
        self.prior = self.replay(264,bracket)
        self.assertIsNone(self.prior['state']['event_id'])
        self.assertEqual(self.prior['movement']['dial_cursor'],257)
        self.prior = self.replay(264,bracket)
        self.assertEqual((self.prior['state']['event_id'],self.prior['state']['value_ft3']),(264,'0.00'))
