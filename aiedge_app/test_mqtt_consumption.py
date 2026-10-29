import copy,json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock
from mqtt_consumption import configuration,fresh_consumption
from mqtt_output import MqttOutput,discovery,broker_config
from test_mqtt_output import Client
from test_reading_format import document
from reading_format import validate
from options import validate as validate_options,InvalidOptions
from service import publication_state

class ConsumptionPublicationTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc)
        doc=document([1000,5]);doc['maximum_rate_per_second']=.2
        revision=validate(doc)[1]
        self.s={'format':doc,'latest':{'captured_at':self.now.isoformat(),'sha256':'b'*64},
                '_timing_event_id':8,'_publication_segment_id':'a'*32,'reading':{'state':'ambiguous','value':None},
                'consumption':dict(state='estimated',event_id=8,segment_id='a'*32,format_id=revision,
                  unit='ft3',source_sha256='b'*64,through_captured_at=self.now.isoformat(),
                  anchor_captured_at=(self.now-timedelta(seconds=30)).isoformat(),
                  observation_accepted=True,value=1.,minimum=.9,maximum=1.1,upper_unbounded=False,
                  unresolved_gap={'reason':'capture_clock_changed','first_event':7,'delta':None})}
    def fresh(self):return fresh_consumption(self.s,90,self.now)
    def test_publishes_relative_even_when_absolute_ambiguous(self):
        x=self.fresh();self.assertEqual(x['value'],1);self.assertEqual(x['coverage'],'observed_segment_only')
        self.assertEqual(x['unresolved_gap']['delta'],None)
    def test_withholds_all_non_numeric_decisions(self):
        for state in ('bounded','ambiguous','within_noise','pending','unavailable','recovering'):
            with self.subTest(state=state):
                self.s['consumption']['state']=state;self.assertIsNone(self.fresh())
    def test_cannot_fill_omitted_or_nonfinite_value(self):
        for value in (None,float('nan'),float('inf'),True,-1):
            with self.subTest(value=value):
                self.s['consumption']['value']=value;self.assertIsNone(self.fresh())
    def test_finite_enclosing_bounds_required(self):
        for delta in ({'minimum':2},{'maximum':.5},{'maximum':None},{'upper_unbounded':True},{'minimum':-1}):
            with self.subTest(delta=delta):
                old=copy.deepcopy(self.s);self.s['consumption'].update(delta)
                self.assertIsNone(self.fresh());self.s=old
    def test_exact_event_even_when_identical_jpeg(self):
        for event in (7,9,True,None):
            self.s['consumption']['event_id']=event;self.assertIsNone(self.fresh())
    def test_hash_format_segment_and_unit_bindings(self):
        for key,value in [('source_sha256','c'*64),('format_id','d'*64),('segment_id','e'*32),('unit','m3'),('observation_accepted',False)]:
            old=copy.deepcopy(self.s);self.s['consumption'][key]=value
            self.assertIsNone(self.fresh());self.s=old
    def test_old_timestamp_cannot_borrow_fresh_frame(self):
        self.s['consumption']['through_captured_at']=(self.now-timedelta(seconds=1)).isoformat()
        self.assertIsNone(self.fresh())
    def test_future_stale_or_naive_timestamp_rejected(self):
        for stamp in ((self.now+timedelta(seconds=1)).isoformat(),(self.now-timedelta(seconds=91)).isoformat(),self.now.replace(tzinfo=None).isoformat()):
            self.s['latest']['captured_at']=stamp;self.s['consumption']['through_captured_at']=stamp
            self.assertIsNone(self.fresh())
    def test_anchor_zero_has_strict_boundary(self):
        c=self.s['consumption'];c.update(state='anchored',value=0,minimum=0,maximum=0,anchor_captured_at=self.now.isoformat())
        self.assertEqual(self.fresh()['value'],0)
        c['value']=.1;self.assertIsNone(self.fresh())
    def test_missing_or_unbounded_rate_is_not_inferred_from_cadence(self):
        for value in (None,0,-1,True,float('inf')):
            self.s['format']['maximum_rate_per_second']=value;self.assertIsNone(self.fresh())
    def test_default_options_keep_existing_behavior(self):
        self.assertEqual(validate_options({})['mqtt_output_mode'],'reading')
        self.assertEqual(validate_options({'mqtt_output_mode':'gas_consumption'})['mqtt_output_mode'],'gas_consumption')
        for value in ('gas',None,[],True):
            with self.assertRaises(InvalidOptions):validate_options({'mqtt_output_mode':value})
    def test_discovery_separates_old_history_and_explicit_resets(self):
        oldtopic,oldbase,old=discovery('f'*32,self.s['format'],30)
        topic,base,cfg=configuration('f'*32,self.s['format'],30,'gas_consumption',discovery)
        self.assertNotEqual(topic,oldtopic);self.assertNotEqual(base,oldbase)
        self.assertEqual(cfg['device_class'],'gas');self.assertEqual(cfg['state_class'],'total')
        self.assertEqual(cfg['last_reset_value_template'],'{{ value_json.last_reset }}')
        self.assertNotIn('state_class',old)
    def test_gas_mode_rejects_incompatible_unit_before_connection(self):
        self.s['format']['unit']='kWh'
        with self.assertRaisesRegex(ValueError,'mqtt_gas_unit_invalid'):
            configuration('f'*32,self.s['format'],30,'gas_consumption',discovery)
    def test_reset_payload_survives_identical_snapshot_restart(self):
        self.assertEqual(self.fresh(),fresh_consumption(copy.deepcopy(self.s),90,self.now))
    def worker(self,d):
        self.clients=[]
        def factory(*args,**kwargs):
            c=Client(*args,**kwargs);self.clients.append(c);return c
        return MqttOutput(d,lambda:self.s,30,provider=lambda:broker_config({'host':'fixture','port':1883}),
                          client_factory=factory,output_mode='gas_consumption')
    def test_transport_ack_expiry_duplicates_and_segment_reset(self):
        with tempfile.TemporaryDirectory() as d:
            w=self.worker(d)
            try:
                w.publish_snapshot(self.s);client=self.clients[0]
                states=[x for x in client.sent if x[0].endswith('/state')]
                self.assertEqual(len(states),1);self.assertFalse(states[0][3])
                self.assertEqual(json.loads(states[0][1])['value'],1)
                w.publish_snapshot(self.s)
                self.assertEqual(len([x for x in client.sent if x[0].endswith('/state')]),1)
                self.s['_publication_segment_id']='c'*32
                self.s['consumption'].update(segment_id='c'*32,state='anchored',value=0,minimum=0,maximum=0,anchor_captured_at=self.now.isoformat())
                w.publish_snapshot(self.s)
                states=[x for x in client.sent if x[0].endswith('/state')]
                self.assertEqual(len(states),2);self.assertEqual(json.loads(states[-1][1])['value'],0)
                self.assertNotEqual(json.loads(states[0][1])['last_reset'],json.loads(states[-1][1])['last_reset'])
                self.s['consumption']['state']='ambiguous';w.publish_snapshot(self.s)
                self.assertEqual(client.sent[-1][1],'offline')
            finally:w.close()
    def test_partial_transport_failure_remains_retryable(self):
        with tempfile.TemporaryDirectory() as d:
            w=self.worker(d);w.publish_snapshot(self.s);client=self.clients[0]
            self.s['consumption'].update(value=2,minimum=1.9,maximum=2.1)
            original=w._publish
            def fail(topic,payload,retain=False):
                if topic.endswith('/attributes'):raise ValueError('mqtt_publish_unconfirmed')
                original(topic,payload,retain)
            w._publish=fail
            try:
                with self.assertRaises(ValueError):w.publish_snapshot(self.s)
                self.assertIsNone(w.last_key)
                w._publish=original;w.publish_snapshot(self.s)
                self.assertEqual(w.last_key[0],2)
            finally:w.close()
    def test_service_race_withholds_consumption(self):
        store=Mock();store.publication_frame.side_effect=[(8,self.s['latest']),(9,self.s['latest'])]
        recog=Mock();fmt=Mock();cons=Mock()
        fmt.evaluate.return_value={'state':'unavailable','value':None}
        fmt.status.return_value={'revision':validate(self.s['format'])[1],'format':self.s['format']}
        cons.status.return_value=self.s['consumption']
        self.assertIsNone(publication_state(store,recog,fmt,cons)['consumption'])
    def test_service_passes_exact_durable_record(self):
        store=Mock();store.publication_frame.return_value=(8,self.s['latest'])
        recog=Mock();fmt=Mock();cons=Mock()
        fmt.evaluate.return_value={'state':'unavailable','value':None}
        fmt.status.return_value={'revision':validate(self.s['format'])[1],'format':self.s['format']}
        cons.status.return_value=self.s['consumption']
        self.assertEqual(publication_state(store,recog,fmt,cons)['consumption'],self.s['consumption'])

if __name__=='__main__':unittest.main()
