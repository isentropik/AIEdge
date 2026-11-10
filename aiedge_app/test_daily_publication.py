"""Offline daily MQTT regressions; no network, camera, or live store."""
import copy,json,unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock,patch
from daily_mqtt import DailyPublisher
from service import publication_state
import test_mqtt_consumption as fixtures

class DailyPublicationTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.ConsumptionPublicationTests();fixture.setUp();self.snapshot=copy.deepcopy(fixture.s)
        self.clock=1000.;self.wall=datetime.now(timezone.utc)
        self.result=dict(day=self.wall.date().isoformat(),lower='10.00',upper='15.00',
                         segment_id=self.snapshot['_publication_segment_id'],
                         through=dict(event_id=8,source_sha256='b'*64,
                                      captured_at=self.snapshot['latest']['captured_at'],
                                      format_id=self.snapshot['consumption']['format_id']),
                         before={'event_id':1},after={'event_id':2})
        self.output=Mock(base='meter',interval=30,config={'unique_id':'meter','device':{}})
        self.store=Mock();db=Mock();db.execute.return_value=[]
        self.store.connect.return_value.__enter__=Mock(return_value=db)
        self.store.connect.return_value.__exit__=Mock(return_value=False)
        self.publisher=DailyPublisher(self.store)
        for p in (patch.dict('os.environ',TZ='UTC'),
                  patch('daily_mqtt.time.monotonic',side_effect=lambda:self.clock),
                  patch('daily_mqtt.daily_records',return_value=[]),
                  patch('daily_mqtt.daily_range',side_effect=lambda *a,**k:copy.deepcopy(self.result))):
            p.start();self.addCleanup(p.stop)
    def test_estimate_separate_bounds_and_identity_unchanged(self):
        self.result.update(lower='52.04',upper='62.24')
        original=copy.deepcopy(self.result); snapshot=copy.deepcopy(self.snapshot)
        self.publish(); payload=self.payloads()[-1]
        self.assertEqual(payload['label'],'52.04–62.24 ft³')
        self.assertEqual(payload['low_use_estimate']['label'],'≈52 ft³')
        self.assertEqual(payload['low_use_estimate']['value_ft3'],'52.04')
        for key,value in original.items(): self.assertEqual(payload[key],value)
        self.assertEqual(self.result,original);self.assertEqual(self.snapshot,snapshot)
    def test_estimate_explicit_assumption_not_likelihood(self):
        self.prime(); e=self.payloads()[-1]['low_use_estimate']
        self.assertEqual(e['method'],'lower_bound_assumption_v1')
        self.assertIn('assumes no additional consumption',e['assumption'])
        self.assertIn('Not a measured total',e['assumption'])
        self.assertIn('Unknown gaps remain unknown',e['assumption'])
    def test_estimate_zero_is_not_missing_or_filled_gap(self):
        self.result.update(lower='0.00',upper='25.00');self.publish()
        self.assertEqual(self.payloads()[-1]['low_use_estimate']['label'],'≈0 ft³')
        self.assertEqual(self.payloads()[-1]['upper'],'25.00')
        self.assertIsNone(self.snapshot['consumption']['unresolved_gap']['delta'])
    def test_estimate_invalid_bounds_fail_closed(self):
        for lo,hi in [('NaN','10'),('0','Infinity'),('-1','10'),('11','10')]:
            with self.subTest(lo=lo,hi=hi):
                self.publisher.reset();self.result.update(lower=lo,upper=hi);self.publish()
                self.assertEqual(self.payloads()[-1],{})
    def test_estimate_updates_with_qualified_range(self):
        self.prime();self.clock+=301;self.result.update(lower='53.47',upper='63.67')
        self.publish();p=self.payloads()[-1]
        self.assertEqual(p['low_use_estimate']['value_ft3'],'53.47')
        self.assertEqual(p['through'],self.result['through'])
    def test_estimate_removed_when_daily_unavailable(self):
        self.prime();self.clock+=301
        with patch('daily_mqtt.daily_range',side_effect=ValueError('no midnight bracket')):self.publish()
        self.assertEqual(self.payloads()[-1],{})

    def payloads(self):
        return [json.loads(c.args[1]) for c in self.output._publish.call_args_list if c.args[0]=='meter/daily_range']
    def publish(self,s=None):self.publisher.publish(self.output,s if s is not None else self.snapshot)
    def prime(self):self.publish();self.assertEqual(self.payloads()[-1]['label'],'10.00–15.00 ft³')
    def pending(self):
        s=copy.deepcopy(self.snapshot);s.update(consumption=None,reading={'state':'pending'},_daily_publication_pending=True);return s
    def test_pending_keeps_original_label_without_publication(self):
        self.prime();before=copy.deepcopy(self.payloads());self.clock+=10;self.publish(self.pending())
        self.assertEqual(self.payloads(),before)
        self.assertEqual(self.publisher.key[0].isoformat(),self.result['day'])
    def test_repeated_pending_does_not_renew_expiry(self):
        self.prime()
        for offset in (10,300,659):self.clock=1000+offset;self.publish(self.pending())
        self.assertEqual(len(self.payloads()),1)
        self.clock=1660;self.publish(self.pending());self.assertEqual(self.payloads()[-1],{})
    def test_no_previous_good_value_is_unavailable(self):
        self.publish(self.pending());self.assertEqual(self.payloads(),[{}])
    def test_reset_does_not_resurrect_cached_value(self):
        self.prime();self.publisher.reset();self.publish(self.pending());self.assertEqual(self.payloads()[-1],{})
    def test_blocked_snapshot_clears_previous_label(self):
        self.prime();s=self.pending();s['_daily_publication_pending']=False;self.publish(s);self.assertEqual(self.payloads()[-1],{})
    def test_missing_pending_marker_clears(self):
        self.prime();s=self.pending();s.pop('_daily_publication_pending');self.publish(s);self.assertEqual(self.payloads()[-1],{})
    def test_changed_segment_clears(self):
        self.prime();s=self.pending();s['_publication_segment_id']='c'*32;self.publish(s);self.assertEqual(self.payloads()[-1],{})
    def test_changed_format_clears(self):
        self.prime();s=self.pending();s['format']['maximum_rate_per_second']*=2;self.publish(s);self.assertEqual(self.payloads()[-1],{})
    def test_changed_unit_clears(self):
        self.prime();s=self.pending();s['format']['unit']='m3';self.publish(s);self.assertEqual(self.payloads()[-1],{})
    def test_midnight_clears_previous_day(self):
        self.prime()
        with patch('daily_mqtt.datetime') as dt:
            dt.now.return_value=self.wall+timedelta(days=1);self.publish(self.pending())
        self.assertEqual(self.payloads()[-1],{})
    def test_timezone_change_clears(self):
        self.prime()
        with patch.dict('os.environ',TZ='America/Los_Angeles'):self.publish(self.pending())
        self.assertEqual(self.payloads()[-1],{})
    def test_calculation_failure_is_not_hidden(self):
        self.prime();self.clock+=301
        with patch('daily_mqtt.daily_range',side_effect=ValueError('missing midnight bracket')):self.publish()
        self.assertEqual(self.payloads()[-1],{})
    def test_endpoint_mismatch_is_not_hidden(self):
        self.prime();self.clock+=301;self.result['through']['event_id']=9;self.publish();self.assertEqual(self.payloads()[-1],{})
    def test_recovery_publishes_new_event_without_changing_gap(self):
        self.prime();self.publish(self.pending());self.clock+=301
        s=copy.deepcopy(self.snapshot);s['_timing_event_id']=9;s['consumption']['event_id']=9
        self.result['through']['event_id']=9;self.result['upper']='16.00';self.publish(s)
        self.assertEqual(self.payloads()[-1]['through']['event_id'],9)
        self.assertEqual(self.payloads()[-1]['upper'],'16.00')
        self.assertEqual(s['consumption']['unresolved_gap'],self.snapshot['consumption']['unresolved_gap'])
    def state(self,*,blocked=False,race=False,behind=True,state='estimated'):
        store=Mock();store.publication_frame.side_effect=[(8,self.snapshot['latest']),(9 if race else 8,self.snapshot['latest'])]
        store.publication_blocked.return_value=blocked
        rec=Mock();fmt=Mock();fmt.status.return_value={'format':self.snapshot['format'],'revision':self.snapshot['consumption']['format_id']}
        fmt.evaluate.return_value=dict(self.snapshot['reading'],format_id=self.snapshot['consumption']['format_id'])
        worker=Mock();worker.status.return_value=copy.deepcopy(self.snapshot['consumption']);worker.status.return_value.update(event_id=7 if behind else 8,state=state)
        return publication_state(store,rec,fmt,worker)
    def test_service_marks_accounting_lag_and_daily_retains(self):
        self.prime();s=self.state();self.assertTrue(s['_daily_publication_pending']);self.assertIsNone(s['consumption']);self.publish(s);self.assertEqual(len(self.payloads()),1)
    def test_service_marks_capture_during_snapshot(self):
        self.assertTrue(self.state(race=True,behind=False)['_daily_publication_pending'])
    def test_service_never_marks_durable_block_or_invalid_decision(self):
        for kwargs in ({'blocked':True},{'state':'invalid'},{'race':True,'state':'unavailable'}):
            with self.subTest(kwargs=kwargs):self.assertFalse(self.state(**kwargs)['_daily_publication_pending'])
    def test_service_complete_snapshot_is_not_pending(self):
        self.assertFalse(self.state(behind=False)['_daily_publication_pending'])

    def test_same_event_pending_accounting_is_marked(self):
        self.assertTrue(self.state(behind=False,state='pending')['_daily_publication_pending'])
    def test_stale_complete_snapshot_is_not_retained(self):
        self.prime();s=copy.deepcopy(self.snapshot)
        stamp=(self.wall-timedelta(seconds=1000)).isoformat()
        s['latest']['captured_at']=stamp;s['consumption']['through_captured_at']=stamp
        self.publish(s);self.assertEqual(self.payloads()[-1],{})
    def test_invalid_timezone_fails_closed(self):
        self.prime()
        with patch.dict('os.environ',TZ='Invalid/Zone'):self.publish(self.pending())
        self.assertEqual(self.payloads()[-1],{})
    def test_unknown_gap_survives_pending_and_recovery(self):
        self.prime();before=copy.deepcopy(self.snapshot)
        self.publish(self.pending());self.clock+=301;self.publish()
        self.assertEqual(self.snapshot,before)
        self.assertIsNone(self.snapshot['consumption']['unresolved_gap']['delta'])

if __name__=='__main__':unittest.main()
