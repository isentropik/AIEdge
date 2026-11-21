from datetime import datetime, timezone
import random
from unittest.mock import Mock
from threading import Event
from time import monotonic, sleep
import unittest
from zoneinfo import ZoneInfo
from gas_periods import GasPeriods, bounds_at, limits, micros, window, HOUR


class ClockPeriodTests(unittest.TestCase):
    def test_overlapping_publications_do_not_double_count_or_fill_a_gap(self):
        rows=[(0,15,11,14),(0,20,12,18),(15,30,4,6),(35,45,2,3)]
        self.assertEqual(limits(rows,0,30),(15,20))
        self.assertEqual(limits(rows,0,45),(17,None))
        self.assertEqual(limits(rows,30,35),(None,None))
        self.assertEqual(limits([(0,15,0,0)],3,6),(0,0))
        self.assertEqual(limits([(3,7,0,5),(0,10,20,25)],0,10),(20,25))

    def test_every_supported_bound_contains_the_known_consumption(self):
        rng=random.Random(35)
        for _ in range(35):
            true=[0]
            for i in range(36):
                true.append(true[-1]+rng.randrange(8))
            intervals=[]
            for i in range(45):
                a=rng.randrange(36); b=rng.randrange(a+1,37); use=true[b]-true[a]
                intervals.append((a,b,max(0,use-rng.randrange(4)),use+rng.randrange(4)))
            intervals.sort(key=lambda q:(q[1],q[0]))
            for a in range(34):
                b=rng.randrange(a+1,37)
                lo,hi=limits(intervals,a,b)
                if lo is not None:self.assertLessEqual(lo,true[b]-true[a])
                if hi is not None:self.assertGreaterEqual(hi,true[b]-true[a])

    def test_fall_back_and_partial_bins_follow_wall_clock(self):
        start=micros('2026-11-01T01:53:12.123456-07:00'); end=start+HOUR
        zone=ZoneInfo('America/Los_Angeles')
        data=window([(start,end,100,110)],start,end,15,zone)
        bins=data['bins']
        local=lambda s:datetime.fromisoformat(s).astimezone(zone)
        self.assertEqual(local(bins[0]['end']).strftime('%H:%M %z'),'01:00 -0800')
        self.assertEqual(local(bins[-1]['end']).strftime('%H:%M:%S'),'01:53:12')
        self.assertEqual(len(bins),5)
        for left,right in zip(bins,bins[1:]):
            self.assertEqual(left['end'],right['start'])
            self.assertEqual(local(left['end']).minute%15,0)
        self.assertEqual(data['lower'],'1.00')
    def test_advancing_endpoint_keeps_completed_work_at_its_own_timestamp(self):
        def report(last):
            def src(i):
                return dict(camera='meter',format_id='f',clock_id='c',event_id=i,source_sha256=f'{i:064x}',
                            captured_at=datetime.fromtimestamp(900*i,timezone.utc).isoformat())
            def span(a,b):
                return dict(start=src(a),through=src(b),lower=str(b-a),upper=str(b-a))
            return dict(unknown_gaps_preserved=True,timezone='UTC',through=src(last),hour=span(last-4,last),
                        quarters=[span(i,i+1) for i in range(last-4,last)],label='4–4 ft³')
        first,second=report(11),report(12)
        go=Event();started=Event()
        def read(*_):
            started.set();go.wait(2)
            return [[dict(entity_id='sensor.recent',state=first['label'],attributes=first)]]
        fetch=Mock(side_effect=read);service=GasPeriods('sensor.recent',fetch)
        self.assertEqual(service.snapshot(first)['status'],'loading');self.assertTrue(started.wait(2))
        self.assertEqual(service.snapshot(second)['status'],'loading');self.assertEqual(fetch.call_count,1)
        go.set()
        deadline=monotonic()+3
        while monotonic()<deadline:
            result=service.snapshot(second)
            if result.get('through')==second['through']:break
            if result['status']=='ready':self.assertEqual(result['through'],first['through'])
            sleep(.01)
        self.assertEqual(result['through'],second['through'])
        self.assertEqual(result['periods']['1']['lower'],'4.00')
        self.assertIsNone(result['periods']['24']['upper'])
        self.assertEqual(service.snapshot(None)['status'],'no_source')
        cold=GasPeriods('sensor.recent',fetch)
        daily={k:v for k,v in second.items() if k not in ('hour','quarters','label')}
        cold.snapshot({},daily)
        deadline=monotonic()+3
        while monotonic()<deadline:
            recovered=cold.snapshot({},daily)
            if recovered.get('status')=='ready':break
            sleep(.01)
        self.assertEqual(recovered['through'],first['through'])
        self.assertEqual(recovered['periods']['1']['upper'],'4.00')

    def test_prefixes_equal_independent_queries_and_keep_open_upper(self):
        rows=[(0,5,2,8),(2,6,0,4),(4,8,3,5),(1,8,2,12),(10,12,2,3)]
        stops=[3,5,6,8,10,12]
        self.assertEqual(bounds_at(rows,0,stops),[limits(rows,0,b) for b in stops])
        self.assertEqual(bounds_at(rows,0,stops)[-1],(5,None))
