import copy,json,unittest
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from unittest.mock import Mock,patch
from zoneinfo import ZoneInfo
from recent_usage import recent_ranges,RecentPublisher
from daily_constraints import WorkLimit


class RecentRangeTests(unittest.TestCase):
    def setUp(self):
        self.zone=ZoneInfo('UTC')
        self.document=dict(unit='ft3',pipeline_id='p',maximum_rate_per_second='.2',dials=[dict(value_per_revolution=1000)])
        self.contexts={'c':('p','f',1)}
        self.rows=[]
        start=datetime(2026,11,8,23,30,tzinfo=timezone.utc)
        for i in range(61):
            value=Decimal(100)+Decimal(i)/10
            source=dict(event_id=i+1,captured_at=(start+timedelta(seconds=i*60)).isoformat(),
                        camera='saved',clock_id='boot',context_id='c',format_id='f',monotonic_us=(i+1)*60000000,source_sha256='a'*64)
            self.rows.append(dict(event_id=i+1,event_observation=source,unit='ft3',segment_id='s',
                observation_accepted=True,upper_unbounded=True,delta=None,
                absolute=dict(unit='ft3',provenance='single_image',bounds=dict(state='bounded',wraps_register=False,
                    ranges=[dict(lower=str(value),upper=str(value+Decimal('.02')))]))))
    def solve(self):return recent_ranges(None,self.rows,self.document,self.contexts,self.zone)
    def test_hour_and_adjacent_quarters_cross_midnight(self):
        r=self.solve();self.assertEqual((r['hour']['lower'],r['hour']['upper']),('5.98','6.02'))
        self.assertEqual(len(r['quarters']),4)
        self.assertEqual([(q['lower'],q['upper']) for q in r['quarters']],[('1.48','1.52')]*4)
        self.assertEqual(r['quarters'][0]['start'],r['hour']['start'])
        for a,b in zip(r['quarters'],r['quarters'][1:]):self.assertEqual(a['through'],b['start'])
    def test_historical_gap_outside_window_does_not_widen_usage(self):
        for row in self.rows:row['unresolved_gap']={'first_event':1,'delta':None,'reason':'old_storage_outage'}
        before=copy.deepcopy(self.rows);self.assertEqual(self.solve()['hour']['upper'],'6.02');self.assertEqual(self.rows,before)
    def test_internal_gap_keeps_extra_turn(self):
        for row in self.rows[25:]:
            bands=row['absolute']['bounds']['ranges'];v=bands[0]
            bands.append(dict(lower=str(Decimal(v['lower'])+5),upper=str(Decimal(v['upper'])+5)))
        self.rows=self.rows[:21]+self.rows[25:]
        r=self.solve();self.assertEqual(r['hour']['upper'],'11.02');self.assertTrue(all(x['delta'] is None for x in self.rows))
    def test_missing_hour_boundary_withholds(self):
        self.rows=self.rows[1:]
        with self.assertRaisesRegex(ValueError,'boundary_missing'):self.solve()
    def test_missing_quarter_boundary_withholds(self):
        self.rows=self.rows[:12]+self.rows[16:]
        with self.assertRaisesRegex(ValueError,'boundary_missing'):self.solve()
    def test_actual_endpoints_not_invented_quarter_readings(self):
        self.rows.pop(15)
        q=self.solve()['quarters'];self.assertEqual(q[0]['through']['event_id'],15)
        self.assertEqual(q[0]['duration_seconds'],'840')
    def test_clock_change_withholds(self):
        self.rows[30]['event_observation']['clock_id']='other'
        with self.assertRaisesRegex(ValueError,'source_changed'):self.solve()
    def test_unverified_context_withholds(self):
        self.rows[30]['event_observation']['context_id']='other'
        with self.assertRaisesRegex(ValueError,'source_changed'):self.solve()
    def test_compatible_context_transition_preserves_unknown(self):
        self.rows[30]['event_observation']['context_id']='new';self.contexts['new']=('p','f',31)
        self.assertEqual(self.solve()['hour']['upper'],'6.02')
    def test_nonmonotonic_timestamp_withholds(self):
        self.rows[30]['event_observation']['captured_at']=self.rows[29]['event_observation']['captured_at']
        with self.assertRaisesRegex(ValueError,'unordered_time'):self.solve()
    def test_register_rollover_not_silently_unwrapped(self):
        self.rows[-1]['absolute']['bounds']['ranges']=[dict(lower='1',upper='2')]
        with self.assertRaises(ValueError):self.solve()
    def test_work_exhaustion_returns_no_partial_intervals(self):
        with patch('daily_constraints.MAX_WORK',0),self.assertRaises(WorkLimit):self.solve()
    def test_dst_fold_uses_elapsed_seconds(self):
        self.zone=ZoneInfo('America/Los_Angeles')
        start=datetime(2026,11,1,8,30,tzinfo=timezone.utc)
        for i,row in enumerate(self.rows):row['event_observation']['captured_at']=(start+timedelta(minutes=i)).astimezone(self.zone).isoformat()
        self.assertEqual(self.solve()['hour']['duration_seconds'],'3600')
    def test_record_cap_withholds(self):
        with patch('recent_usage.MAX_RECORDS',60),self.assertRaisesRegex(ValueError,'history_limit'):self.solve()


class RecentPublicationTests(unittest.TestCase):
    def setUp(self):
        from test_daily_publication import DailyPublicationTests
        self.fixture=DailyPublicationTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture;self.publisher=RecentPublisher(f.store);self.output=f.output;self.snapshot=f.snapshot
        self.obs=dict(f.result['through'],segment_id=f.result['segment_id'])
        self.result=dict(label='1.00–1.20 ft³',through=f.result['through'],timezone='UTC',hour={},quarters=[],segment_id=self.obs['segment_id'])
        self.fresh=patch('recent_usage.fresh_range',side_effect=lambda s,*a:None if s.get('consumption') is None else self.obs).start()
        self.addCleanup(patch.stopall)
        patch('recent_usage.daily_records',return_value=[]).start()
        self.calculate=patch('recent_usage.recent_ranges',side_effect=lambda *a,**k:copy.deepcopy(self.result)).start()
    def publish(self,s=None):self.publisher.publish(self.output,self.snapshot if s is None else s)
    def payloads(self):return [json.loads(c.args[1]) for c in self.output._publish.call_args_list if c.args[0]=='meter/recent_usage']
    def test_separate_discovery_and_expiry(self):
        self.publish();config=json.loads(self.output._publish.call_args_list[0].args[1])
        self.assertEqual(config['name'],'Gas used last hour');self.assertEqual(config['expire_after'],660)
        self.assertEqual(self.payloads()[-1],self.result)
    def test_throttle_and_refresh_do_not_change_source_time(self):
        self.publish();self.fixture.clock+=10;self.publish();self.assertEqual(len(self.payloads()),1)
        self.fixture.clock+=300;self.publish();self.assertEqual(len(self.payloads()),2)
        self.assertEqual(self.payloads()[0]['through'],self.payloads()[1]['through'])
    def test_fault_invalidates_before_refresh_deadline(self):
        self.publish();s=copy.deepcopy(self.snapshot);s['consumption']=None;self.publish(s)
        self.assertEqual(self.payloads()[-1],{})
    def test_pending_does_not_renew_expiry(self):
        self.publish();s=self.fixture.pending();self.publish(s);self.assertEqual(len(self.payloads()),1)
        self.fixture.clock+=660;self.publish(s);self.assertEqual(self.payloads()[-1],{})
    def test_changed_pending_segment_invalidates(self):
        self.publish();s=self.fixture.pending();s['_publication_segment_id']='different';self.publish(s)
        self.assertEqual(self.payloads()[-1],{})
    def test_mismatched_endpoint_withholds(self):
        self.result['through']['event_id']=999;self.publish();self.assertEqual(self.payloads()[-1],{})
    def test_work_limit_publishes_unavailable_not_partial(self):
        self.calculate.side_effect=WorkLimit;self.publish();self.assertEqual(self.payloads()[-1],{})
    def test_restart_rediscovery(self):
        self.publish();self.publisher.reset();self.publish()
        self.assertEqual(sum(c.args[0].endswith('/config') for c in self.output._publish.call_args_list),2)

    def test_daily_failure_does_not_prevent_recent_publication(self):
        from mqtt_output import MqttOutput
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            daily=Mock();daily.publish.side_effect=ValueError('midnight bracket absent')
            worker=MqttOutput(directory,lambda:self.snapshot,30,daily=daily,output_mode='gas_consumption')
            worker.client=Mock();worker.connected.set()
            worker._publish_snapshot=Mock();worker._publish_range=Mock()
            worker.publish_snapshot(self.snapshot)
            daily.recent.publish.assert_called_once_with(worker,self.snapshot)
            self.assertEqual(worker.daily_error,'daily_publication_failed')
            self.assertIsNone(worker.recent_error)

    def test_recent_failure_does_not_change_daily_result(self):
        from mqtt_output import MqttOutput
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            daily=Mock();daily.recent.publish.side_effect=ValueError('budget')
            worker=MqttOutput(directory,lambda:self.snapshot,30,daily=daily,output_mode='gas_consumption')
            worker.client=Mock();worker.connected.set()
            worker._publish_snapshot=Mock();worker._publish_range=Mock()
            worker.publish_snapshot(self.snapshot)
            daily.publish.assert_called_once_with(worker,self.snapshot)
            self.assertIsNone(worker.daily_error)
            self.assertEqual(worker.status()['recent_error'],'recent_publication_failed')

if __name__=='__main__':unittest.main()
