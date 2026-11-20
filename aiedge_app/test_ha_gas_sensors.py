import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from ha_gas_sensors import GasSensors, check_register, projected_sensors


class GasSensorTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'register.sqlite3'
        self.sensors=GasSensors(tmp.name)
        self.now=datetime.now(timezone.utc)
        self.point=dict(event_id=1,source_sha256='a'*64,captured_at=self.now.isoformat(),register_ft3=1000,
                        maximum_rate_per_second=.2,segment_id='s',format_id='f',value=4)

    def later(self, seconds=10, **changes):
        return {**self.point,'event_id':2,'captured_at':(self.now+timedelta(seconds=seconds)).isoformat(),**changes}

    def test_reverse_register_rejected_across_restart(self):
        self.assertIsNone(check_register(self.path,'meter',self.point))
        self.assertEqual(check_register(Path(str(self.path)),'meter',self.later(register_ft3=900)),'register_moved_backward')
        self.assertIsNone(check_register(self.path,'meter',self.later(register_ft3=1000)))

    def test_jump_and_replay(self):
        self.assertIsNone(check_register(self.path,'meter',self.point))
        self.assertIsNone(check_register(self.path,'meter',self.point))
        self.assertEqual(check_register(self.path,'meter',self.later(register_ft3=1200)),'register_rate_exceeded')
        self.assertIsNone(check_register(self.path,'meter',self.later(register_ft3=1100)))
        self.assertEqual(check_register(self.path,'meter',self.point),'register_out_of_order')

    def test_equal_id_conflicting_hash_and_reversed_clock(self):
        self.assertIsNone(check_register(self.path,'one',self.point))
        for revised in [dict(self.point,source_sha256='b'*64),self.later(seconds=-1)]:
            self.assertEqual(check_register(self.path,'one',revised),'register_out_of_order')
        self.assertIsNone(check_register(self.path,'another',self.later(register_ft3=100)))

    def test_ambiguous_register_keeps_last_checkpoint(self):
        check_register(self.path,'one',self.point)
        self.assertEqual(check_register(self.path,'one',self.later(register_ft3=None)),'register_ambiguous')
        self.assertEqual(check_register(self.path,'one',self.later(register_ft3=900)),'register_moved_backward')

    def call(self, point, tick, clock='boot'):
        observation={k:point[k] for k in ('source_sha256','format_id','captured_at','event_id')}
        observation.update(monotonic_us=tick,clock_id=clock,context_id='context')
        return self.sensors.interval_values({'consumption':{'event_observation':observation}},point)

    def test_adjacent_delta_and_rate_and_zero(self):
        self.assertEqual(self.call(self.point,100),{})
        next_point=self.later(value=5)
        self.assertEqual(self.call(next_point,10000100),{'delta':1,'flow':6})
        self.assertEqual(self.call(next_point,10000100),{'delta':1,'flow':6})
        self.assertEqual(self.call(self.later(value=5,event_id=3),20000100),{'delta':0,'flow':0})

    def test_unknown_or_changed_context_withholds_rates(self):
        for change in [dict(value=3),dict(value=50),dict(event_id=3),dict(segment_id='new'),dict(format_id='new')]:
            self.sensors.reset_connection()
            self.call(self.point,100)
            self.assertEqual(self.call(self.later(**change),10000100),{})
        self.sensors.reset_connection()
        self.call(self.point,100)
        self.assertEqual(self.call(self.later(),10000100,'new-clock'),{})
        self.sensors.interval_values({},None)
        self.assertEqual(self.call(self.later(event_id=3),20000100,'new-clock'),{})

    def test_numeric_bounds_are_distinct_from_meter_total(self):
        records=[]
        output=SimpleNamespace(base='aiedge/test',interval=15,config={'unique_id':'fixture','device':{}},
                               _publish=lambda topic,payload,retain:records.append((topic,json.loads(payload),retain)))
        self.sensors.discover(output)
        self.assertEqual(len(records),26)
        self.assertEqual(len({r[0] for r in records}),26)
        enabled=[cfg for _,cfg,_ in records if cfg['enabled_by_default']]
        self.assertEqual([cfg['unique_id'] for cfg in enabled],['fixture_daily_nominal','fixture_absolute_nominal'])
        self.assertEqual(enabled[1]['device_class'],'gas')
        self.assertNotIn('last_reset_value_template',enabled[1])
        self.assertNotIn('state_class',enabled[0])
        self.assertEqual(len(list(projected_sensors())),17)
        totals=[r[1] for r in records if r[1].get('state_class')=='total']
        self.assertEqual([v['unique_id'] for v in totals],['fixture_absolute_nominal','fixture_confirmed_register'])
        self.assertTrue(all(r[2] for r in records))
        self.assertNotIn('expire_after', enabled[0])
        self.assertNotIn('availability_topic', enabled[0])
        self.assertEqual(enabled[0]['state_topic'], 'aiedge/test/daily_nominal')
        self.assertTrue(all(cfg['expire_after'] > 0 for _, cfg, _ in records if not cfg['enabled_by_default']))

    def publish_meter(self, event, bands, *, seconds=None, segment='s', usage=0, digest=None):
        from nominal_register import AbsolutePublisher
        if not hasattr(self, 'meter'):
            self.meter = AbsolutePublisher(self.path)
            self.messages = []
        seconds = event * 10 if seconds is None else seconds
        out = SimpleNamespace(base='local',config={'unique_id':'fixture'},
                              _publish=lambda topic,body,retain:self.messages.append((json.loads(body),retain)))
        obs = dict(self.point, event_id=event,source_sha256=digest or str(event).zfill(64),
                   segment_id=segment,minimum=usage,maximum=usage,maximum_rate_per_second=.5,
                   captured_at=(self.now+timedelta(seconds=seconds)).isoformat())
        source = {k:obs[k] for k in ('event_id','captured_at','format_id','source_sha256')}
        source.update(camera='fixture',clock_id='boot',context_id='context',monotonic_us=seconds*1000000)
        c = dict(anchor_captured_at=self.now.isoformat(), event_observation=source,
                 absolute=dict(unit='ft3',provenance='temporal_consumption_bounds',
                               bounds=dict(state='bounded',wraps_register=False,
                                           ranges=[dict(lower=x,upper=y) for x,y in bands])))
        doc = {'dials':[{'value_per_revolution':10000,'position_error':.1},{'value_per_revolution':5,'position_error':.1}]}
        self.meter.publish(out,obs,dict(consumption=c,format=doc))
        if self.messages:
            state,retained = self.messages[-1]
            self.assertTrue(retained)
            return state

    def test_absolute_nominal_tracks_motion_and_skips_duplicate(self):
        bounds = [(100,100.1),(105,105.1),(110,110.1),(115,115.1)]
        self.assertEqual(float(self.publish_meter(1,bounds)['value_ft3']),105.05)
        self.publish_meter(1,bounds)
        self.assertEqual(len(self.messages),1)
        state = self.publish_meter(2,[(105.31,105.4),(110.31,110.4)])
        self.assertEqual(float(state['value_ft3']),105.31)
        self.assertEqual(self.publish_meter(1,bounds)['event_id'],2)
        self.assertEqual(self.publish_meter(2,bounds,digest='e'*64)['reason'],'out_of_order')

    def test_absolute_nominal_holds_after_restart_gap_and_branch_correction(self):
        from nominal_register import AbsolutePublisher
        first = self.publish_meter(1,[(101,101)])
        self.meter = AbsolutePublisher(self.path)
        held = self.publish_meter(3,[])
        self.assertEqual((held['event_id'],held['measured_at'],held['value_ft3']),
                         (1, first['measured_at'],first['value_ft3']))
        self.assertEqual(self.publish_meter(4,[(106,106)],segment='new')['reason'],'whole_turn_unconfirmed')
        refreshed = self.publish_meter(5,[(101.5,101.6)],segment='new')
        self.assertEqual((refreshed['status'],float(refreshed['value_ft3'])),('partial_coverage',101.5))

    def test_absolute_confirmed_whole_turn_and_reverse_checks(self):
        self.assertIsNone(self.publish_meter(1,[]))
        self.publish_meter(2,[(405,405)])
        self.assertEqual(self.publish_meter(3,[(406,406)],seconds=21)['reason'],'no_continuous_candidate')
        self.assertEqual(self.publish_meter(4,[(404,404)])['reason'],'no_continuous_candidate')
        self.assertEqual(float(self.publish_meter(5,[(410,410)],usage=5)['value_ft3']),410)

    def test_daily_nominal_midpoint(self):
        from daily_mqtt import nominal_estimate
        for lo,hi,expected in [('9.83','20.03','14.93'),('8.29','18.50','13.40'),
                               ('0','0','0.00'),('0','0.01','0.01'),('2.50','2.50','2.50')]:
            original={'lower':lo,'upper':hi}
            self.assertEqual(nominal_estimate(original)['value_ft3'],expected)
            self.assertEqual(original,{'lower':lo,'upper':hi})
        for lo,hi in [('2','1'),('-1','1'),('NaN','3'),('0','Infinity')]:
            with self.assertRaises(ValueError):
                nominal_estimate({'lower':lo,'upper':hi})

    def test_nominal_restart_gap_and_midnight(self):
        from nominal_daily import NominalPublisher
        sent = []
        output = SimpleNamespace(base='test', config={'unique_id':'fixture'},
                                 _publish=lambda t,p,r:sent.append((t,json.loads(p),r)))
        publisher = NominalPublisher(self.path)
        day = self.now.date()
        origin = datetime.combine(day, datetime.min.time(), timezone.utc)
        def obs(event, lo, hi, segment='s', start=1):
            return dict(self.point, captured_at=(origin+timedelta(minutes=event)).isoformat(),
                        segment_started_at=(origin+timedelta(minutes=start)).isoformat(),
                        minimum=lo, maximum=hi, event_id=event, segment_id=segment)
        def publish(point=None, daily=None):
            publisher.publish(output, point, daily, day, 'UTC')
            topic, state, retain = sent[-1]
            self.assertEqual((topic, retain), ('test/daily_nominal',True))
            return state
        first = obs(10,3,4)
        full = dict(day=day.isoformat(),timezone='UTC',through=first,segment_id='s',
                    nominal_estimate={'value_ft3':'14.93','method':'range_midpoint_v1','assumption':'midpoint'},
                    lower='9.83',upper='20.03',low_use_estimate={'value_ft3':'9.83'})
        self.assertEqual(publish(first,full)['value_ft3'],'14.93')
        held = publish()
        self.assertEqual((held['status'],held['event_id'],held['measured_at']),
                         ('held_at_last_reading',10,first['captured_at']))
        publisher = NominalPublisher(self.path)
        self.assertEqual(publish(),held)
        partial = publish(obs(12,5,6))
        self.assertEqual((partial['value_ft3'],partial['upper_ft3']),('15.93',None))
        self.assertEqual(publish(obs(13,5,6))['value_ft3'],'15.93')
        self.assertEqual(publish(obs(14,2,3,'new',14))['value_ft3'],'17.93')
        self.assertEqual(publish(first,full)['event_id'],14)
        day += timedelta(days=1)
        opening = publish(first,full)
        self.assertEqual((opening['status'],opening['value_ft3'],opening['event_id']),
                         ('opening_balance','0.00',None))
        origin = datetime.combine(day, datetime.min.time(), timezone.utc)
        self.assertEqual(publish(obs(2,100,101,start=-30))['value_ft3'],'0.00')
        self.assertEqual(publish(obs(3,104,105,start=-30))['value_ft3'],'3.00')
        self.assertEqual(publish()['status'],'held_at_last_reading')

    def test_mqtt_daily_math_failure_keeps_a_numeric_nominal(self):
        from unittest.mock import patch
        from test_daily_publication import DailyPublicationTests
        from test_mqtt_consumption import ConsumptionPublicationTests
        daily = DailyPublicationTests()
        daily.setUp()
        self.addCleanup(daily.doCleanups)
        worker = ConsumptionPublicationTests().worker(str(self.path.parent))
        self.addCleanup(worker.close)
        worker.daily = daily.publisher
        worker.publish_snapshot(daily.snapshot)
        def state():
            return [json.loads(msg[1]) for msg in worker.client.sent if msg[0].endswith('/daily_nominal')][-1]
        self.assertEqual(state()['value_ft3'], '12.50')
        daily.clock += 301
        with patch('daily_mqtt.daily_range',side_effect=ValueError('calculation failed')):
            worker.publish_snapshot(daily.snapshot)
        self.assertEqual(state()['status'],'held_at_last_reading')
        self.assertEqual(state()['value_ft3'],'12.50')
        self.assertIsNone(worker.nominal_error)
        self.assertIsNone(daily.snapshot['consumption']['unresolved_gap']['delta'])

    def test_mqtt_register_regression_survives_worker_restart(self):
        from test_mqtt_consumption import ConsumptionPublicationTests
        fixture=ConsumptionPublicationTests()
        fixture.setUp()
        snapshot=fixture.s
        c=snapshot['consumption']
        stamp=fixture.now-timedelta(seconds=5)
        c.update(state='ambiguous',value=None,anchor_captured_at=(stamp-timedelta(seconds=20)).isoformat())
        bounds={'state':'bounded','wraps_register':False,'ranges':[]}
        c['absolute']={'state':'bounded','unit':'ft3','provenance':'temporal_consumption_bounds','bounds':bounds}
        for index,(candidate,expected) in enumerate([(850,800),(750,None),(855,800)]):
            worker=fixture.worker(str(self.path.parent))
            try:
                event=index+8
                snapshot['_timing_event_id']=event
                t=(stamp+timedelta(seconds=index)).isoformat()
                sha=str(index+1)*64
                snapshot['latest'].update(captured_at=t,sha256=sha)
                c.update(event_id=event,through_captured_at=t,source_sha256=sha)
                bounds['ranges']=[{'lower':candidate,'upper':candidate+1}]
                worker.publish_snapshot(snapshot)
                messages={msg[0].split('/')[-1]:json.loads(msg[1]) for msg in worker.client.sent
                          if msg[0].endswith(('/meter_diagnostics','/segment_range'))}
                self.assertEqual(messages['segment_range'].get('register_ft3'),expected)
                diagnostic=messages['meter_diagnostics']
                self.assertEqual(diagnostic.get('confirmed_register'),expected)
                self.assertEqual(diagnostic['event_id'],event)
                if expected is None:
                    self.assertEqual(diagnostic['status'],'register_moved_backward')
                    self.assertNotIn('delta',diagnostic)
            finally:
                worker.close()
