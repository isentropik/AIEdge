import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from chart_hours import ChartHours
from hourly_photo import carried_difference, difference, project
from meter_history import millis


class ChartHoursTests(unittest.TestCase):
    meter = 'sensor.meter'
    daily = 'sensor.daily'
    hour = datetime(2026,11,22,18,tzinfo=timezone.utc)

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


if __name__=='__main__':
    unittest.main()
