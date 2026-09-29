import copy,json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import patch
from mqtt_output import MqttOutput,broker_config,discovery,fresh_state,instance_id,supervisor_mqtt
from reading_format import validate
from test_reading_format import document

class Info:
    def wait_for_publish(self,timeout):pass
    def is_published(self):return True
class Client:
    def __init__(self,*args,**kwargs):self.sent=[];self.subscriptions=[];self.will=None;self.credentials=None
    def will_set(self,*args,**kwargs):self.will=(args,kwargs)
    def username_pw_set(self,*args):self.credentials=args
    def tls_set_context(self,context):self.tls=context
    def reconnect_delay_set(self,**kwargs):pass
    def connect_async(self,*args,**kwargs):self.destination=(args,kwargs)
    def loop_start(self):self.on_connect(self,None,None,SimpleNamespace(is_failure=False),None)
    def subscribe(self,*args,**kwargs):self.subscriptions.append((args,kwargs))
    def publish(self,topic,payload,qos,retain):self.sent.append((topic,payload,qos,retain));return Info()
    def disconnect(self):pass
    def loop_stop(self):pass

class MqttTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.clients=[]
        self.doc=document([1000,100]);self.revision=validate(self.doc)[1]
        self.snapshot={'format':self.doc,'latest':{'captured_at':datetime.now(timezone.utc).isoformat(),'sha256':'b'*64},
            'reading':{'state':'estimated','value':120,'source_sha256':'b'*64,'format_id':self.revision,'unit':'ft3'}}
        def factory(*args,**kwargs):
            c=Client(*args,**kwargs);self.clients.append(c);return c
        self.worker=MqttOutput(self.temp.name,lambda:self.snapshot,30,provider=lambda:broker_config({'host':'fixture','port':'1883','ssl':False,'username':'fixture','password':'test'}),client_factory=factory)
    def tearDown(self):self.worker.close();self.temp.cleanup()
    def test_identity_survives_restart(self):
        self.assertEqual(instance_id(self.temp.name),self.worker.identity)
    def test_discovery_is_unique_and_not_total_increasing(self):
        topic,base,cfg=discovery(self.worker.identity,self.doc,30)
        self.assertTrue(topic.startswith('homeassistant/sensor/aiedge_'))
        self.assertNotIn('state_class',cfg);self.assertEqual(cfg['unit_of_measurement'],'ft³')
        changed=copy.deepcopy(self.doc);changed['unit']='m3'
        self.assertNotEqual(discovery(self.worker.identity,changed,30)[0],topic)
        changed=copy.deepcopy(self.doc);changed['pipeline_id']='c'*64
        self.assertEqual(discovery(self.worker.identity,changed,30)[0],topic)
    def test_publish_ack_order_no_retained_measurement(self):
        self.worker.publish_snapshot(self.snapshot);client=self.clients[0]
        self.assertEqual(client.will[0][1],'offline')
        self.assertEqual(client.credentials,('fixture','test'))
        state=next(i for i,row in enumerate(client.sent) if row[0].endswith('/state'))
        available=next(i for i,row in enumerate(client.sent) if row[1]=='online')
        self.assertLess(state,available);self.assertFalse(client.sent[state][3]);self.assertEqual(client.sent[state][2],1)
        result=json.loads(client.sent[state][1]);self.assertEqual(result['value'],120);self.assertFalse(result['accuracy_verified'])
        count=len(client.sent);self.worker.publish_snapshot(self.snapshot);self.assertEqual(len(client.sent),count)
    def test_invalid_or_stale_reading_marks_sensor_unavailable(self):
        self.worker.publish_snapshot(self.snapshot);client=self.clients[0]
        self.snapshot['reading']['state']='ambiguous';self.worker.publish_snapshot(self.snapshot)
        self.assertEqual(client.sent[-1][1],'offline');self.assertEqual(self.worker.state,'waiting_for_reading')
        self.snapshot['reading']['state']='estimated'
        self.snapshot['latest']['captured_at']=(datetime.now(timezone.utc)-timedelta(seconds=91)).isoformat()
        self.assertIsNone(fresh_state(self.snapshot,90))
        self.snapshot['latest']['captured_at']=(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat()
        self.assertIsNone(fresh_state(self.snapshot,90))
    def test_mismatched_image_never_published(self):
        self.snapshot['reading']['source_sha256']='c'*64
        self.worker.publish_snapshot(self.snapshot)
        self.assertFalse(any(row[0].endswith('/state') for row in self.clients[0].sent))
    def test_ha_birth_republishes_discovery_and_current_state(self):
        self.worker.publish_snapshot(self.snapshot);client=self.clients[0];client.sent.clear()
        self.worker._on_message(client,None,SimpleNamespace(topic='homeassistant/status',payload=b'online'))
        self.worker.publish_snapshot(self.snapshot)
        self.assertTrue(any(row[0].endswith('/config') for row in client.sent))
        self.assertTrue(any(row[0].endswith('/state') for row in client.sent))
    def test_format_change_retires_old_availability(self):
        self.worker.publish_snapshot(self.snapshot);old=self.clients[0]
        changed=copy.deepcopy(self.doc);changed['unit']='m3';self.snapshot['format']=changed
        self.worker.publish_snapshot(self.snapshot)
        self.assertEqual(old.sent[-1][1],'offline');self.assertEqual(len(self.clients),2)
        self.assertFalse(any(row[0].endswith('/state') for row in self.clients[-1].sent))
    def test_unconfirmed_publish_is_not_reported_successful(self):
        self.worker.connect(self.doc)
        self.worker.client.publish=lambda *a,**k:SimpleNamespace(wait_for_publish=lambda **k:None,is_published=lambda:False)
        with self.assertRaisesRegex(ValueError,'unconfirmed'):self.worker.publish_snapshot(self.snapshot)
        self.assertNotEqual(self.worker.state,'publishing')
    def test_invalid_broker_settings_and_no_supervisor_token(self):
        for data in ({'host':'a/b','port':1883},{'host':'fixture','port':0},{'host':'fixture','port':True},{'host':'fixture','port':1883.5},{'host':'fixture','port':float('inf')},{'host':'fixture','port':'1e3'},{'host':'fixture','port':1883,'ssl':'false'},{'host':'fixture','port':1883,'username':'x'},{'host':'fixture','port':1883,'protocol':'5'}):
            with self.assertRaises(ValueError):broker_config(data)
        with patch.dict('os.environ',{'SUPERVISOR_TOKEN':''}):
            with self.assertRaisesRegex(ValueError,'token_unavailable'):supervisor_mqtt()

if __name__=='__main__':unittest.main()
