import copy
import sqlite3
import unittest
from contextlib import nullcontext
from datetime import datetime, timezone
from unittest.mock import Mock
from meter_history import frame_ids, rebuild


class MeterHistoryTests(unittest.TestCase):
    def setUp(self):
        self.rows=[]
        self.frames={}
        self.midnight=1795248000000
        for event,seconds,value in [(1,-4,90),(2,2,90),(3,20,92),(5,30,92),(6,35,93),(7,40,94)]:
            t=datetime.fromtimestamp(self.midnight/1000+seconds,timezone.utc).isoformat()
            a=dict(event_id=event,measured_at=t,source_sha256=format(event,'064x'),value_ft3=str(value),
                   status='nominal',method='minimum_supported_forward_movement')
            self.rows.append(dict(entity_id='sensor.meter',state=str(value),attributes=a))
            self.frames[event]=(t,a['source_sha256'])
        def source(i):
            return dict(event_id=i,captured_at=self.frames[i][0],source_sha256=self.frames[i][1],camera='meter',format_id='f')
        self.daily=dict(day='2026-11-21',timezone='America/Los_Angeles',before=source(1),after=source(2),through=source(7))
        self.track=dict(midnight=self.midnight,first_meter='94',format='f',points=[[self.midnight+40000,9,7,1]])
    def run_history(self):
        return rebuild(lambda entity,start,end:[self.rows],lambda camera,ids:{i:self.frames[i] for i in ids if i in self.frames},'sensor.meter',self.daily,self.track)
    def test_event_gaps_basis_change_and_independent_bounds(self):
        self.daily.update(lower=100,upper=102)
        p=self.run_history()
        self.assertEqual(p['anchor'],self.track['points'][0][:3])
        self.assertEqual(p['offset'],5)
        self.assertEqual([(v[1],v[2]) for v in p['points']],[(0,2),(2,3),(2,5),(3,6)])
        self.assertNotEqual(p['points'][1][-1],p['points'][2][-1])
    def test_unqualified_midnight_or_checkpoint_is_withheld(self):
        for change in ('pre_moved','after_digest','wrong_amount','wrong_format','wrong_time','wrong_entity','missing_frame'):
            with self.subTest(change=change):
                self.setUp()
                if change=='pre_moved':
                    self.rows[0]['attributes']['value_ft3']=self.rows[0]['state']='89'
                elif change=='after_digest':self.daily['after']['source_sha256']='a'*64
                elif change=='wrong_amount':self.track['first_meter']='95'
                elif change=='wrong_format':self.track['format']='other'
                elif change=='wrong_time':self.track['points'][0][0]+=1
                elif change=='wrong_entity':self.rows[-1]['entity_id']='sensor.other'
                else:del self.frames[7]
                self.assertIsNone(self.run_history())
    def test_stale_duplicate_and_conflicting_reading(self):
        held=copy.deepcopy(self.rows[1])
        held['attributes']['status']='held_at_last_reading'
        self.rows.insert(2,held)
        self.rows[3]['attributes']['source_sha256']='c'*64
        p=self.run_history()['points']
        self.assertEqual([v[2] for v in p],[2,5,6])
        self.assertNotEqual(p[0][-1],p[1][-1])
    def test_lookup_uses_camera_and_exact_event(self):
        with sqlite3.connect(':memory:') as db:
            db.executescript("CREATE TABLE frames(camera,frame_id,captured_at,sha256); CREATE TABLE capture_events(event_id,camera,frame_id); INSERT INTO frames VALUES('a','f','t','x'),('b','f','wrong','y'); INSERT INTO capture_events VALUES(1,'a','f'),(2,'b','f');")
            store=Mock()
            store.connect.side_effect=lambda:nullcontext(db)
            self.assertEqual(frame_ids(store,'a',[1,2]),{1:('t','x')})
            self.assertEqual(frame_ids(store,'a',[]),{})

    def test_verified_movement_survives_range_recorder_failure_and_is_cached(self):
        from gas_trend import GasTrend
        from time import monotonic,sleep
        calls=[]
        def fetch(entity,start,end):
            if entity=='sensor.bounds':raise OSError()
            calls.append(entity)
            return [self.rows]
        cache=GasTrend('sensor.bounds',fetch,meter_entity='sensor.meter',lookup=lambda camera,ids:self.frames)
        limit=monotonic()+3
        while True:
            result=cache.snapshot(self.daily,self.track)
            if result.get('meter_prefix'):break
            if monotonic()>=limit:self.fail('archive failed to load independently')
            sleep(.01)
        self.assertEqual(result['day'],self.daily['day'])
        self.assertEqual(result['groups'],[])
        self.assertEqual(result['meter_prefix']['offset'],5)
        cache.snapshot(self.daily,dict(self.track,points=self.track['points']+[[self.midnight+60000,10,8,1]]))
        self.assertEqual(calls,['sensor.meter'])
