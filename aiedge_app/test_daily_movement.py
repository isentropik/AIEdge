from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase

from nominal_daily import NominalPublisher, advance


class DailyMovementTests(TestCase):
    day = date(2026, 11, 21)
    zone = 'America/Los_Angeles'
    origin = datetime(2026, 11, 21, 21, tzinfo=timezone.utc)

    def sample(self, event, absolute, *, stamp=None, limits=None, status='nominal'):
        at = (stamp or self.origin + timedelta(seconds=event)).isoformat()
        obs = dict(event_id=event, captured_at=at, source_sha256=f'{event:064x}', format_id='f',
                   segment_id='s', segment_started_at=self.origin.isoformat(), minimum=0, maximum=0)
        meter = dict(event_id=event, measured_at=at, source_sha256=obs['source_sha256'],
                     value_ft3=str(absolute), method='minimum_supported_forward_movement', status=status)
        full = None
        if limits:
            lo, hi = limits
            full = dict(day=self.day.isoformat(), timezone=self.zone, through=obs.copy(), segment_id='s',
                        lower=lo, upper=hi, low_use_estimate={'value_ft3':lo},
                        nominal_estimate={'method':'range_midpoint_v1','assumption':'midpoint','value_ft3':str((lo+hi)/2)})
        return obs, full, meter

    def step(self, record, event, absolute, **options):
        obs, full, meter = self.sample(event, absolute, **options)
        return advance(record, obs, full, self.day, self.zone, meter)

    def test_bounds_do_not_move_headline_even_outside_the_new_bounds(self):
        state = self.step(None, 1, 1000, limits=(10,20))
        for event, bounds in [(2,(11,23)), (3,(11,13)), (4,(0,100))]:
            state = self.step(state,event,1000,limits=bounds)
            published = state['state']
            self.assertEqual(published['value_ft3'], '15.00')
            self.assertEqual((published['lower_ft3'],published['upper_ft3'],published['bounds_event_id']),(*bounds,event))
        state = self.step(state,5,'1000.012')
        self.assertEqual((state['state']['value_ft3'],state['state']['bounds_event_id']),('15.01',4))

    def test_no_roundoff_drift_or_double_count_when_repeated(self):
        state = self.step(None, 1, 1000, limits=(10,20))
        for event in range(2,302):
            absolute = Decimal(1000) + Decimal(event-1)/1000
            state = self.step(state,event,absolute)
        self.assertEqual(state, self.step(state,301,absolute))
        self.assertEqual(state['state']['value_ft3'],'15.30')
        self.assertEqual(len(state['movement']['points']),2)

    def test_wrong_source_time_regression_and_unconfirmed_meter(self):
        base = self.step(None,1,1000,limits=(10,20))
        obs, full, meter = self.sample(2,2000)
        for bad in [dict(meter,source_sha256='a'*64),dict(meter,status='held_at_last_reading'),
                    dict(meter,measured_at=self.origin.isoformat()),dict(meter,value_ft3='NaN'),
                    dict(meter,value_ft3='bad'),dict(meter,value_ft3='999')]:
            result = advance(base,obs,full,self.day,self.zone,bad)
            self.assertEqual(result['state']['event_id'],1)
            self.assertEqual(result['state']['value_ft3'],'15.00')
        same = self.step(base,1,1005)
        self.assertEqual(same['movement']['last_meter'],'1000')
        later = self.step(base,3,1001)
        self.assertEqual(self.step(later,2,1002),later)

    def test_missing_meter_can_receive_new_bounds_at_their_own_time(self):
        base = self.step(None,1,1000,limits=(10,20))
        obs, full, meter = self.sample(2,1000,limits=(12,14))
        held = advance(base,obs,full,self.day,self.zone,None)
        self.assertEqual((held['state']['event_id'],held['state']['bounds_event_id']),(1,2))
        self.assertEqual(held['state']['bounds_measured_at'],obs['captured_at'])
        self.assertEqual(held['state']['value_ft3'],'15.00')
        other = dict(full,through=dict(full['through'],format_id='other'))
        self.assertEqual(advance(base,obs,other,self.day,self.zone,None)['state']['bounds_event_id'],1)

    def test_unknown_gap_restart_and_mqtt_retry_do_not_add_a_turn(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'state.sqlite'
            out=SimpleNamespace(config={'unique_id':'test'},base='meter',_publish=lambda *args:None)
            worker=NominalPublisher(path)
            def send(event, value, **kwargs):
                obs,full,meter=self.sample(event,value,**kwargs)
                worker.publish(out,obs,full,self.day,self.zone,meter)
            send(1,1000,limits=(10,20))
            def fail(*args):
                raise OSError('ack lost')
            out._publish=fail
            with self.assertRaises(OSError):
                send(4,1001,status='partial_coverage')
            self.assertEqual(worker.sent['event_id'],1)
            worker=NominalPublisher(path)
            out._publish=lambda *args:None
            send(4,1001,status='partial_coverage')
            self.assertEqual((worker.sent['value_ft3'],worker.sent['status']),('16.00','partial_coverage'))
            self.assertEqual([p[3] for p in worker.record['movement']['points']],[0,1])
            send(5,1001)
            self.assertEqual(worker.sent['value_ft3'],'16.00')
            self.assertNotIn('points',worker.sent)

    def test_migrate_exact_or_unpaired_legacy_checkpoint(self):
        with TemporaryDirectory() as tmp:
            worker=NominalPublisher(Path(tmp)/'state.db')
            out=SimpleNamespace(config={'unique_id':'test'},base='meter',_publish=lambda *args:None)
            obs,full,old=self.sample(1,1000,limits=(10,20))
            worker.publish(out,obs,full,self.day,self.zone)
            obs,full,new=self.sample(2,1001,limits=(20,30))
            worker.publish(out,obs,full,self.day,self.zone,new,old)
            self.assertEqual(worker.sent['value_ft3'],'16.00')
        obs, full, meter = self.sample(1,1000,limits=(10,20))
        legacy = advance(None,obs,full,self.day,self.zone)
        migrated = self.step(legacy,2,1004,limits=(20,30))
        self.assertEqual((migrated['state']['value_ft3'],migrated['state']['status']),('15.00','partial_coverage'))

    def test_midnight_resets_and_yesterdays_last_meter_cannot_prime_today(self):
        old=self.step(None,1,1000,limits=(10,20))
        obs,full,meter=self.sample(1,1000,limits=(10,20))
        tomorrow=self.day+timedelta(days=1)
        opening=advance(old,obs,full,tomorrow,self.zone,meter)
        self.assertEqual((opening['state']['value_ft3'],opening['state']['event_id']),('0.00',None))
        obs,_,meter=self.sample(2,1007,stamp=self.origin+timedelta(days=1))
        partial=advance(opening,obs,None,tomorrow,self.zone,meter)
        self.assertEqual((partial['state']['value_ft3'],partial['state']['status']),('0.00','partial_coverage'))
        self.assertIsNone(partial['state']['lower_ft3'])

    def test_worker_publishes_the_same_meter_delta_to_mqtt_and_overview(self):
        from test_daily_publication import DailyPublicationTests
        from test_mqtt_consumption import ConsumptionPublicationTests
        fixture = DailyPublicationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with TemporaryDirectory() as tmp:
            worker = ConsumptionPublicationTests().worker(tmp)
            try:
                worker.daily = fixture.publisher
                snap = fixture.snapshot
                consumption = snap['consumption']
                for i, register in enumerate([405, 405.6]):
                    event = 8+i
                    at = (fixture.wall-timedelta(seconds=20-10*i)).isoformat()
                    digest = str(event)*64
                    source = dict(camera='fixture', clock_id='clock', context_id='context', event_id=event,
                                  captured_at=at, format_id=consumption['format_id'], source_sha256=digest,
                                  monotonic_us=10000000*(1+i))
                    snap['_timing_event_id'] = event
                    snap['latest'].update(captured_at=at,sha256=digest)
                    consumption.update(event_id=event, through_captured_at=at,source_sha256=digest,
                        event_observation=source,absolute=dict(unit='ft3',provenance='temporal_consumption_bounds',
                        bounds=dict(state='bounded',wraps_register=False,ranges=[dict(lower=register,upper=register)])))
                    fixture.result.update(through=source, lower='10.00',upper='15.00' if not i else '12.00')
                    fixture.clock += 301
                    worker.publish_snapshot(snap)
                    mqtt = worker.nominal.sent
                    self.assertEqual(worker.gas_sensors.absolute.sent[1]['event_id'],event)
                    self.assertEqual((mqtt['method'],mqtt['event_id'],mqtt['value_ft3']),
                                     ('nominal_meter_movement_v1',event,'12.50' if i == 0 else '13.10'))
                    overview = worker.status()['usage']
                    self.assertEqual(overview['daily_nominal'],mqtt)
                    self.assertEqual(overview['movement_history']['points'][-1][2],event)
                    self.assertIsNone(consumption['unresolved_gap']['delta'])
            finally:
                worker.close()
