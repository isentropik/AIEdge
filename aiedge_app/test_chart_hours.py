import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from chart_hours import ChartHours,tracked_hour
from hourly_photo import carried_difference, difference, project
from meter_history import millis


class ChartHoursTests(unittest.TestCase):
    meter = 'sensor.meter'
    daily = 'sensor.daily'
    hour = datetime(2026,11,22,18,tzinfo=timezone.utc)

    def test_selected_ten_minute_history_preserves_measured_rate_bounds(self):
        proof=dict(use=.01,bands=[[0,.1]])
        class Ledger:
            def snapshot(self,ticks,*args):
                a,b=ticks[-2:]
                return {b:dict(basis='fine_dial',start=a,end=b,use=.01,bounds=[0,5.1],optical_rate=proof)}
        chart=ChartHours(self.meter,self.daily,lambda *args:[],ledger=Ledger())
        end=millis(self.hour)
        history=chart.snapshot(end,'UTC',minutes=10)
        self.assertEqual(history['rateIntervals'],[[end-600000,end,proof]])

    def test_partial_level_uses_only_same_basis_tracked_change_across_missing_ticks(self):
        step=600000
        d=dict(hours=[dict(start=t*step,end=(t+1)*step,use=2) for t in (0,1,2,5)],
               trackedLevels=[[3*step,25,'a'],[5*step,25.5,'a']])
        self.assertEqual(tracked_hour(0,6*step,d),dict(start=0,end=6*step,use=8.5))
        for leg in d['hours']:
            leg['bounds']=[1,3]
        d['evidenceSpans']=[dict(start=3*step,end=5*step,bounds=[1,5])]
        self.assertEqual(tracked_hour(0,6*step,d),dict(start=0,end=6*step,use=9,bounds=[5,17]))
        d['trackedLevels'][1][1]=32
        self.assertIsNone(tracked_hour(0,6*step,d))
        d['trackedLevels'][1][1]=25.5
        d['trackedLevels'][1][2]='b'
        self.assertIsNone(tracked_hour(0,6*step,d))
        d['trackedLevels'][1]=[5*step,24,'a']
        self.assertIsNone(tracked_hour(0,6*step,d))

    def run_chart(self, rows, cuts=(), zone='UTC', end=None, minutes=60):
        def fetch(entity,start,stop):
            return [[r for dt,r in rows if entity==self.meter and start<=dt<stop]]
        return ChartHours(self.meter,self.daily,fetch,lambda a,b:cuts).snapshot(
            millis(end or self.hour+timedelta(minutes=61)),zone,minutes=minutes)

    def rows(self, observations):
        result=[]
        for i,(seconds,value) in enumerate(observations,1):
            t=self.hour+timedelta(seconds=seconds)
            result.append((t,dict(entity_id=self.meter,state=str(value),attributes=dict(
                measured_at=t.isoformat(),event_id=i,source_sha256=f'{i:064x}',value_ft3=value,
                method='photo_anchored_fine_dial',anchor_event_id=1))))
        return result

    def test_interpolate_then_subtract_at_completed_hours(self):
        observations=[(-2,100),(2,104)]+[(t,104+t/600) for t in range(300,3600,300)]+[(3598,110),(3602,110)]
        data=self.run_chart(self.rows(observations))
        h,=data['hours']
        self.assertEqual((h['opening'],h['closing'],h['use']),(102,110,8))
        self.assertEqual(h['end']-h['start'],3600000)

    def test_first_hour_fetches_only_the_visible_meter_and_does_not_fill_a_break(self):
        observations=self.rows([(i*60,i+100) for i in range(-12,63)])
        queries=[]
        def fetch(entity,start,end):
            queries.append(entity)
            return [[r for when,r in observations if start<=when<end]]
        cut=millis(self.hour+timedelta(minutes=7))
        api=ChartHours(self.meter,self.daily,fetch,lambda a,b:[cut])
        end=millis(self.hour+timedelta(hours=1,seconds=3))
        window=api.published_window(end,'UTC','1',{},None,{})
        self.assertTrue(queries and set(queries)=={self.meter})
        self.assertEqual(len(window['points']),8)
        self.assertIn(millis(self.hour+timedelta(minutes=10)),window['blocked'])
        self.assertIsNone(next(iter(window['openings'].values())))
        self.assertEqual(window['points'][-1][1]-window['points'][-2][1],10)

    def test_verified_window_reuses_the_correct_format_and_keeps_its_source_time(self):
        rows=self.rows([(i*60,i+150) for i in range(-72,74)])
        def fetch(entity,start,end):
            return [[r for when,r in rows if start<=when<end and entity==self.meter]]
        api=ChartHours(self.meter,self.daily,fetch)
        usage={'movement_history':{'format':'a','dial_from':[1,2]}}
        end=millis(self.hour+timedelta(hours=1,seconds=4))
        doc={'unit':'other','dials':[{'value_per_revolution':5,'position_error':.1}]}
        old=api.snapshot(end,'UTC',usage,doc,{},profile=True)
        for t in (end,end+600000):
            quick=api.published_window(t,'UTC','1',usage,doc,{})
            self.assertEqual(quick['asOf'],end)
            self.assertEqual(quick['close'],end-4000)
            self.assertEqual(quick['registerProfile']['points'],[r for r in old['registerProfile']['points']
                if quick['start']-600000<=r[0]<=quick['close']])
        different={'movement_history':{'format':'b','dial_from':[1,2]}}
        self.assertNotIn('asOf',api.published_window(end,'UTC','1',different,doc,{}))

    def test_window_http_route_validates_scale_and_keeps_full_history_separate(self):
        from service import handler
        from unittest.mock import Mock
        from time import time
        charts=Mock()
        mqtt=Mock()
        mqtt.status.return_value={'overview_timezone':'UTC','usage':{}}
        mqtt.daily.evidence_policy={}
        request=object.__new__(handler(Mock(),False,None,mqtt_output=mqtt,chart_hours=charts))
        request.client_address=('127.0.0.1',12345)
        request.headers={'Host':'localhost'}
        request.reply=Mock()
        stamp=int(time()*1000)
        request.path=f'/api/chart-window?end={stamp}&window=1'
        request.read_request()
        charts.published_window.assert_called_once_with(stamp,'UTC','1',{},None,{})
        charts.snapshot.assert_not_called()
        request.path=f'/api/chart-hours?end={stamp}&prepared=1'
        request.read_request()
        charts.prepared.assert_called_once_with(stamp,'UTC',{},None,{})
        for query in ('window=10','minutes=10','window=1&window=6'):
            request.path=f'/api/chart-window?end={stamp}&'+query
            request.read_request()
            self.assertEqual(request.reply.call_args.args[1],400)
        request.path=f'/api/chart-hours?end={stamp}'
        request.read_request()
        charts.snapshot.assert_called_once_with(stamp,'UTC',{},None,{},minutes=60,profile=True)

    def test_partial_day_first_frame_sets_level_without_filling_the_overnight_hour(self):
        first=self.hour+timedelta(seconds=25)
        first_tick=millis(self.hour)+600000
        rows=self.rows([(600,101),(1200,102),(1800,103),(2400,104),(3000,105),(3600,106)])
        published=dict(entity_id=self.daily,state='4',attributes=dict(method='nominal_meter_movement_v1',
            measured_at=(self.hour+timedelta(minutes=55)).isoformat(),day=self.hour.date().isoformat(),
            timezone='UTC',event_id=99,source_sha256='a'*64,value_ft3='4',coverage_started_at=first.isoformat()))
        def fetch(entity,start,stop):
            if entity==self.daily:
                return [[published] if start<=self.hour+timedelta(minutes=55)<stop else []]
            return [[r for t,r in rows if start<=t<stop]]
        class Ledger:
            def snapshot(self,*args):return {}
            def opening(self,stamp,end,*args):
                if stamp==first.isoformat() and end==first_tick:
                    return [end,.1,.05,.15]
        chart=ChartHours(self.meter,self.daily,fetch,ledger=Ledger())
        end=millis(self.hour)+3601000
        fine=chart.snapshot(end,'UTC',minutes=10)
        self.assertEqual(fine['openingLevels'],[[first_tick,.1,.05,.15]])
        self.assertIn([first_tick-600000,first_tick],fine['unknownHours'])
        whole=chart.snapshot(end,'UTC')
        self.assertEqual(whole['openingLevels'],[[end-1000,5.1,None,None]])
        self.assertIn([end-3601000,end-1000],whole['unknownHours'])

    def test_ten_minute_differences_use_bracketing_readings_and_preserve_unknowns(self):
        rows=self.rows([(0,100),(590,100),(610,102),(1200,102),(1800,102)])
        data=self.run_chart(rows, end=self.hour+timedelta(minutes=34),minutes=10)
        self.assertEqual([q['use'] for q in data['hours']],[1,1,0])
        self.assertTrue(all(q['end']-q['start']==600000 for q in data['hours']))
        cut=millis(self.hour+timedelta(seconds=600))
        broken=self.run_chart(rows,[cut],end=self.hour+timedelta(minutes=34),minutes=10)
        self.assertEqual([q['use'] for q in broken['hours']],[0])
        self.assertIn([cut-600000,cut],broken['unknownHours'])
        self.assertIn([cut,cut+600000],broken['unknownHours'])

    def test_bracketed_absolute_endpoints_survive_an_interior_gap(self):
        rows=self.rows([(t,200+t/300) for t in range(0,3601,300)])
        cut=millis(self.hour+timedelta(seconds=1500))
        self.assertEqual(self.run_chart(rows,[cut])['hours'][0]['use'],12)
        self.assertEqual(self.run_chart(rows[:2]+rows[-2:])['hours'][0]['use'],12)
        rows[5][1]['attributes']['status']='held_at_last_reading'
        self.assertEqual(self.run_chart(rows)['hours'][0]['use'],12)

    def test_no_interpolation_inside_a_gap(self):
        rows=self.rows([(-3,100),(2,100),(3598,102),(3602,102)])
        cut=millis(self.hour+timedelta(seconds=1))
        self.assertEqual(self.run_chart(rows,[cut])['hours'],[])

    def test_republished_old_event_between_two_clock_brackets(self):
        rows=self.rows([(-2,100),(2,102),(3600,111)])
        previous=rows[0][1]
        held=dict(previous,attributes=dict(previous['attributes'],status='held_at_last_reading'))
        rows.insert(1,(self.hour,held))
        self.assertEqual(self.run_chart(rows)['hours'][0]['use'],10)
        self.assertFalse(self.run_chart(rows,[millis(self.hour)])['hours'])
        held['attributes']['source_sha256']='f'*64
        self.assertFalse(self.run_chart(rows)['hours'])

    def test_carried_register_cannot_cross_a_known_reset(self):
        end=millis(self.hour)+3600000
        class Ledger:
            def snapshot(self,*args):
                return {end:dict(basis='carried_register',start=end-3600000,end=end,use=2,
                                 carry=dict(start=end-7200000))}
        rows=self.rows([(-3600,100),(0,103),(1800,12),(3600,105)])
        def fetch(entity,start,stop):
            return [[row for t,row in rows if entity==self.meter and start<=t<stop]]
        chart=ChartHours(self.meter,self.daily,fetch,ledger=Ledger())
        self.assertIn([end-3600000,end],chart.snapshot(end,'UTC')['unknownHours'])

    def test_reset_or_missing_register_endpoint_withholds_dot(self):
        rows=self.rows([(0,100),(900,102),(1800,12),(3600,103)])
        self.assertEqual(self.run_chart(rows)['hours'],[])
        held=self.rows([(0,100),(3600,103)])
        held[-1][1]['attributes']['status']='held_at_last_reading'
        self.assertEqual(self.run_chart(held)['hours'],[])

    def test_relative_only_does_not_cross_a_gap(self):
        rows=self.rows([(0,100),(3600,103)])
        for _,r in rows:
            r['attributes']['method']='minimum_supported_forward_movement'
        self.assertEqual(self.run_chart(rows,[millis(self.hour)+10000])['hours'],[])

    def test_multiple_possible_turns_can_bound_a_register_estimate(self):
        ticks_end=millis(self.hour+timedelta(hours=1))
        class Ledger:
            def snapshot(self,*args):
                return {ticks_end:dict(start=ticks_end-3600000,end=ticks_end,basis='fine_dial',bounds=[2.5,7.6])}
        rows=self.rows([(0,100),(3600,103)])
        def fetch(entity,start,stop):
            return [[r for t,r in rows if entity==self.meter and start<=t<stop]]
        chart=ChartHours(self.meter,self.daily,fetch,ledger=Ledger())
        hour,=chart.snapshot(ticks_end,'UTC')['hours']
        self.assertEqual((hour['use'],hour['bounds']),(3,[2.5,7.6]))
        # Ambiguous turn count without an independent register pair has no nominal dot.
        rows.pop()
        chart.closed_page.cache_clear()
        self.assertEqual(chart.snapshot(ticks_end,'UTC')['hours'],[])

    def test_dst_repeated_hour_has_distinct_endpoints_and_measured_zero(self):
        day=datetime(2026,11,1,7,tzinfo=timezone.utc)
        self.hour=day
        rows=self.rows([(t,200) for t in range(0,10801,300)])
        hours=self.run_chart(rows,zone='America/Los_Angeles',end=day+timedelta(hours=3))['hours']
        zone=ZoneInfo('America/Los_Angeles')
        self.assertEqual([(datetime.fromtimestamp(h['end']/1000,zone).hour,h['use']) for h in hours],
                         [(1,0),(1,0),(2,0)])

    def test_failed_recorder_still_returns_verified_optical_hours(self):
        def unavailable(*args):
            raise OSError('offline')
        class Ledger:
            def snapshot(self,ticks,*args):
                return {ticks[-1]:dict(start=ticks[-2],end=ticks[-1],basis='fine_dial',use=0,bounds=[0,.2])}
        h=ChartHours(self.meter,self.daily,unavailable,ledger=Ledger()).snapshot(millis(self.hour),'UTC')
        self.assertEqual(h['missing'],['register','daily'])
        self.assertEqual(h['hours'][0]['use'],0)

    def test_multiple_clients_share_one_build_and_keep_the_original_timestamp(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from unittest.mock import patch
        end=millis(self.hour+timedelta(seconds=4))
        usage={'movement_history':{'format':'a'}}
        doc={'dials':[{'value_per_revolution':5,'position_error':.1}]}
        rows=self.rows([(i*60,150+i) for i in range(-72,74)])
        hours=ChartHours(self.meter,self.daily,
                         lambda entity,a,b:[[r for t,r in rows if a<=t<b and entity==self.meter]])
        compute=hours.snapshot
        started,release=Event(),Event()
        def build(*args,**kwargs):
            started.set()
            self.assertTrue(release.wait(2))
            return compute(*args,**kwargs)
        with patch.object(hours,'snapshot',side_effect=build) as expensive, ThreadPoolExecutor(3) as pool:
            first=pool.submit(hours.prepared,end,'UTC',usage,doc,{})
            self.assertTrue(started.wait(2))
            visitors=[pool.submit(hours.prepared,end+n,'UTC',usage,doc,{}) for n in (1000,2000)]
            release.set()
            for result in [first,*visitors]:
                self.assertEqual(result.result(timeout=5)['end'],end)
            expensive.assert_called_once()

    def test_publication_warms_all_windows_and_restores_without_reader_access(self):
        from chart_hours import BackgroundCharts
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from threading import Event, Thread
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        end=self.hour+timedelta(seconds=5)
        stamp=millis(end)
        usage={'daily_nominal':{'timezone':'UTC','measured_at':end.isoformat()},
               'movement_history':{'format':'f','dial_from':[1,2],'dial_gaps':[]}}
        doc={'dials':[{'value_per_revolution':5,'position_error':.1}]}
        mqtt=SimpleNamespace(status=lambda:{'usage':usage},daily=SimpleNamespace(evidence_policy={}))
        fmt=SimpleNamespace(status=lambda:{'format':doc})
        rows=self.rows([(i*300,1000+i) for i in range(-670,3)])
        def fetch(entity,a,b):
            return [[r for t,r in rows if entity==self.meter and a<=t<b]]
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'chart.json'
            hours=ChartHours(self.meter,self.daily,fetch)
            worker=BackgroundCharts(hours,mqtt,fmt,path)
            ready=Event()
            prepare=worker.prepare
            def finished():
                prepare()
                ready.set()
            with patch.object(worker,'prepare',side_effect=finished):
                thread=Thread(target=worker.run)
                thread.start()
                try:
                    self.assertFalse(path.exists())
                    worker.published.set()
                    self.assertTrue(ready.wait(10))
                    self.assertIsNotNone(worker.completed)
                finally:
                    worker.request_stop()
                    thread.join(2)
                self.assertFalse(thread.is_alive())
            offline=Mock(side_effect=AssertionError('history fetch on first open'))
            hours=ChartHours(self.meter,self.daily,offline)
            BackgroundCharts(hours,mqtt,fmt,path).load()
            full=hours.prepared(stamp+5000,'UTC',usage,doc,{})
            self.assertEqual(full['end'],stamp)
            for scale in ('1','6','12','24','today'):
                self.assertEqual(hours.published_window(stamp+5000,'UTC',scale,usage,doc,{})['asOf'],stamp)
            offline.assert_not_called()
            # A new gap or interval must never hit the old verified chart.
            for t,u in ((stamp+600000,usage),(stamp,{**usage,'movement_history':{**usage['movement_history'],'dial_gaps':[[stamp-100,stamp]]}})):
                with self.assertRaisesRegex(AssertionError,'history fetch'):
                    hours.prepared(t,'UTC',u,doc,{})
            import hashlib
            import json
            original=path.read_bytes()
            prior=json.loads(original.split(b'\n',1)[1])
            prior[0]=5
            payload=json.dumps(prior).encode()
            path.write_bytes(hashlib.sha256(payload).hexdigest().encode()+b'\n'+payload)
            clean=ChartHours(self.meter,self.daily,offline)
            BackgroundCharts(clean,mqtt,fmt,path).load()
            self.assertIsNone(clean.last_profile)
            path.write_bytes(original[:-4])
            clean=ChartHours(self.meter,self.daily,offline)
            BackgroundCharts(clean,mqtt,fmt,path).load()
            self.assertIsNone(clean.last_profile)


class HourlyPhotoTests(unittest.TestCase):
    def test_carry_uses_a_measured_hour_and_preserves_endpoint_bounds(self):
        anchor=dict(value=Decimal('100'),bounds=(Decimal('99'),Decimal('101')))
        close=dict(value=Decimal('105.56'),bounds=(Decimal('105'),Decimal('106')))
        movement=dict(basis='fine_dial',start=0,end=3600000,use=3.17,bounds=[3.1,3.3])
        hour=carried_difference(anchor,movement,close)
        self.assertEqual((hour['opening'],hour['closing'],hour['use']),(103.17,105.56,2.39))
        self.assertEqual(hour['bounds'],[0.70,3.90])
        zero=dict(value=Decimal('103.17'),bounds=(Decimal('103.1'),Decimal('103.3')))
        self.assertEqual(carried_difference(anchor,movement,zero)['use'],0)
        for invalid in (dict(movement,basis='carried_register'),dict(movement,use=3.5),
                        {k:v for k,v in movement.items() if k!='use'}):
            self.assertIsNone(carried_difference(anchor,invalid,close))
        self.assertIsNone(carried_difference(None,movement,close))
        self.assertIsNone(carried_difference(anchor,movement,anchor))

    def test_turn_must_be_unique_and_continuous_from_photo(self):
        ref = dict(event_id=1, captured_at='2026-11-22T23:58:00+00:00')
        end = dict(event_id=2, captured_at='2026-11-22T23:59:00+00:00')
        anchor = ref, Decimal(100), (Decimal(95), Decimal(105))
        sample = [(end, (Decimal('0.95'), Decimal('1.05')))]
        document = dict(dials=[dict(value_per_revolution=5)])
        def estimate(bounds, spans):
            def travel(*args):
                return dict(use=1, bounds=bounds, supported_spans=spans)
            return project(None, document, {}, 1, anchor, sample, travel)
        self.assertEqual(estimate([0, 2], []), [(101, 95, 107)])
        self.assertIsNone(estimate([0, 7], []))
        self.assertIsNone(estimate([0, 2], [(1, 2)]))

    def test_hour_requires_two_consistent_register_estimates(self):
        early = dict(value=Decimal(15), bounds=(Decimal(14), Decimal(16)))
        late = dict(value=Decimal(17), bounds=(Decimal(16), Decimal(18)))
        self.assertIsNone(difference(None, late))
        self.assertIsNone(difference(early, None))
        self.assertIsNone(difference(late, early))
        self.assertEqual(difference(early, late)['bounds'], [0, 4])

    def test_backward_pointer_jitter_requires_overlapping_observed_bands(self):
        ref=dict(event_id=1,captured_at='2026-11-22T23:57:00Z')
        a=dict(event_id=2,captured_at='2026-11-22T23:58:00Z')
        b=dict(event_id=3,captured_at='2026-11-22T23:59:00Z')
        anchor=ref,Decimal(100),(Decimal(95),Decimal(105))
        travel=lambda *args:dict(use=1,bounds=[0,2],supported_spans=[])
        def run(low,high):
            points=[(a,(Decimal('.95'),Decimal('1.05'))),(b,(Decimal(low),Decimal(high)))]
            return project(None,dict(dials=[dict(value_per_revolution=5)]),{},1,anchor,points,travel)
        shared=run('.94','1.04')
        self.assertEqual(shared[0][0],shared[1][0])
        self.assertIsNone(run('.70','.80'))


if __name__=='__main__':
    unittest.main()
