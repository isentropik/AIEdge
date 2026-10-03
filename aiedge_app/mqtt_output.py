"""Optional HA MQTT output. No image uploads or commands to the camera."""
import hashlib,json,math,os,re,ssl,threading,time,urllib.request,uuid
from datetime import datetime,timezone
from pathlib import Path
import paho.mqtt.client as mqtt
from capture import NoRedirect
from performance import Timings
from setup_store import Setup
from reading_format import validate

UNITS={'ft3':'ft³','m3':'m³','L':'L','gal_us':'gal','kWh':'kWh'}

def supervisor_mqtt():
    token=os.environ.get('SUPERVISOR_TOKEN','')
    if not token:raise ValueError('supervisor_token_unavailable')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    request=urllib.request.Request('http://supervisor/services/mqtt',headers={'Authorization':'Bearer '+token})
    with opener.open(request,timeout=5) as response:
        body=response.read(65537)
        if len(body)>65536:raise ValueError('mqtt_service_response_too_large')
        result=json.loads(body)
    if result.get('result')!='ok' or not isinstance(result.get('data'),dict):raise ValueError('mqtt_service_unavailable')
    return broker_config(result['data'])

def broker_config(data):
    host=data.get('host');port=data.get('port');secure=data.get('ssl',False)
    if not isinstance(host,str) or not host or len(host)>253 or any(c.isspace() or c in '/@?#' for c in host):
        raise ValueError('invalid_mqtt_host')
    if type(port) not in (int,str) or (isinstance(port,str) and not re.fullmatch('[0-9]{1,5}',port)):
        raise ValueError('invalid_mqtt_port')
    try:port=int(port)
    except (ValueError,TypeError):raise ValueError('invalid_mqtt_port') from None
    if not 1<=port<=65535 or type(secure) is not bool:raise ValueError('invalid_mqtt_connection')
    if data.get('protocol','3.1.1')!='3.1.1':raise ValueError('unsupported_mqtt_protocol')
    username,password=data.get('username',''),data.get('password','')
    if not isinstance(username,str) or not isinstance(password,str) or bool(username)!=bool(password):
        raise ValueError('invalid_mqtt_credentials')
    return dict(host=host,port=port,ssl=secure,username=username,password=password)

def instance_id(directory):
    path=Path(directory)/'instance-id'
    if path.exists():
        with path.open('rb') as stream:blob=stream.read(65)
        if len(blob)>64:raise ValueError('invalid_instance_id')
        identity=blob.decode('ascii').strip()
    else:
        identity=uuid.uuid4().hex;Setup._atomic(path,(identity+'\n').encode('ascii'))
    if not re.fullmatch('[a-f0-9]{32}',identity):raise ValueError('invalid_instance_id')
    return identity

def discovery(identity,document,interval):
    # Different physical units/scales must not silently reinterpret sensor history.
    physical={'unit':document['unit'],'dials':[{k:d[k] for k in ('index','value_per_revolution')} for d in document['dials']]}
    suffix=hashlib.sha256(json.dumps(physical,sort_keys=True).encode()).hexdigest()[:16]
    unique='aiedge_'+identity+'_'+suffix
    base='aiedge/'+identity+'/'+suffix
    config={'name':'Meter reading','unique_id':unique,'state_topic':base+'/state',
            'value_template':'{{ value_json.value }}','availability_topic':base+'/availability',
            'payload_available':'online','payload_not_available':'offline','expire_after':max(90,interval*3),
            'unit_of_measurement':UNITS[document['unit']],
            'device_class':'energy' if document['unit']=='kWh' else 'volume',
            'device':{'identifiers':['aiedge_'+identity],'name':'AIEdge','manufacturer':'AIEdge','model':'Remote meter reader'},
            'json_attributes_topic':base+'/attributes'}
    # No total_increasing state class: cumulative accounting is not validated yet.
    return 'homeassistant/sensor/'+unique+'/config',base,config

def fresh_state(snapshot,max_age,clock=None):
    reading=snapshot.get('reading',{});frame=snapshot.get('latest')
    if reading.get('state')!='estimated' or not frame:return None
    value=reading.get('value')
    if type(value) not in (int,float):return None
    try:
        if not math.isfinite(value):return None
    except OverflowError:return None
    if reading.get('source_sha256')!=frame.get('sha256'):return None
    try:
        captured=datetime.fromisoformat(frame['captured_at'].replace('Z','+00:00'))
        if captured.tzinfo is None:return None
        age=((clock or datetime.now(timezone.utc))-captured).total_seconds()
    except (ValueError,TypeError,KeyError):return None
    if not 0<=age<=max_age:return None
    return {'value':reading['value'],'captured_at':frame['captured_at'],'source_sha256':frame['sha256'],
            'format_id':reading['format_id'],'accuracy_verified':False}

class MqttOutput:
    def __init__(self,directory,snapshot,interval,provider=supervisor_mqtt,client_factory=mqtt.Client,*,performance=None):
        self.performance=performance if performance is not None else Timings()
        self.identity=instance_id(directory);self.snapshot=snapshot;self.interval=interval
        self.provider=provider;self.client_factory=client_factory;self.stop=threading.Event()
        self.connected=threading.Event();self.rediscover=threading.Event();self.state='starting';self.error=None
        self.client=None;self.base=None;self.configuration=None;self.last_payload=None
    def status(self):return {'state':self.state,'error':self.error}
    def _on_connect(self,client,userdata,flags,reason,properties):
        if reason.is_failure:self.error='mqtt_connection_rejected';return
        self.connected.set();self.rediscover.set();client.subscribe('homeassistant/status',qos=1)
    def _on_disconnect(self,client,userdata,flags,reason,properties):
        self.connected.clear()
        if self.state!='error':self.state='disconnected'
    def _on_message(self,client,userdata,message):
        if message.topic=='homeassistant/status' and message.payload==b'online':self.rediscover.set()
    def _publish(self,topic,payload,retain=False):
        info=self.client.publish(topic,payload,qos=1,retain=retain)
        info.wait_for_publish(timeout=5)
        if not info.is_published():raise ValueError('mqtt_publish_unconfirmed')
    def connect(self,document):
        credentials=self.provider();self.configuration,self.base,self.config=discovery(self.identity,document,self.interval)
        self.connected.clear()
        client=self.client_factory(mqtt.CallbackAPIVersion.VERSION2,client_id='aiedge-'+self.identity[:16],protocol=mqtt.MQTTv311)
        self.client=client
        client.on_connect=self._on_connect;client.on_disconnect=self._on_disconnect;client.on_message=self._on_message
        client.will_set(self.base+'/availability','offline',qos=1,retain=True)
        if credentials['username']:client.username_pw_set(credentials['username'],credentials['password'])
        if credentials['ssl']:client.tls_set_context(ssl.create_default_context())
        client.reconnect_delay_set(min_delay=2,max_delay=30)
        client.connect_timeout=5
        client.connect_async(credentials['host'],credentials['port'],keepalive=30);client.loop_start()
        if not self.connected.wait(8):raise ValueError('mqtt_connection_timeout')
        self._publish(self.base+'/availability','offline',True)
        self.state='connected';self.last_payload=None
    def publish_snapshot(self,snapshot):
        with self.performance.measure('mqtt_publication') as sample:
            sample.outcome=self._publish_snapshot(snapshot)
    def _publish_snapshot(self,snapshot):
        document=snapshot.get('format')
        if not document:
            if self.client and self.connected.is_set():self._publish(self.base+'/availability','offline',True)
            self.state='waiting_for_format';return 'rejected'
        target,base,config=discovery(self.identity,document,self.interval)
        if not self.client or target!=self.configuration or not self.connected.is_set():
            self.close();self.connect(document)
        if self.rediscover.is_set():
            self._publish(self.configuration,json.dumps(self.config,ensure_ascii=False),True)
            self.rediscover.clear();self.last_payload=None
        state=fresh_state(snapshot,max(90,self.interval*3))
        if state and state['format_id']!=validate(document)[1]:state=None
        payload=json.dumps(state,sort_keys=True,allow_nan=False) if state else None
        if payload is None:
            if self.last_payload!='offline':self._publish(self.base+'/availability','offline',True)
            self.last_payload='offline';self.state='waiting_for_reading';return 'rejected'
        outcome='duplicate'
        if payload!=self.last_payload:
            # Ack the new value before advertising availability. Never retain a reading.
            self._publish(self.base+'/state',payload)
            self._publish(self.base+'/attributes',json.dumps({k:v for k,v in state.items() if k!='value'}))
            self._publish(self.base+'/availability','online',True)
            self.last_payload=payload
            outcome='success'
            self.performance.publication_ack(snapshot.get('_timing_event_id'),state['source_sha256'])
        self.state='publishing';self.error=None
        return outcome
    def close(self):
        client=self.client
        if client:
            try:
                if self.connected.is_set():self._publish(self.base+'/availability','offline',True)
            except Exception:pass
            try:client.disconnect()
            finally:client.loop_stop();self.client=None;self.connected.clear()
    def run(self):
        try:
            while not self.stop.is_set():
                try:self.publish_snapshot(self.snapshot())
                except Exception as exc:
                    # Never expose broker responses, credentials or arbitrary exception strings.
                    self.error=str(exc) if isinstance(exc,ValueError) and re.fullmatch('[a-z_]+',str(exc)) else 'mqtt_connection_failed'
                    self.state='error';self.close()
                self.stop.wait(5 if self.state!='error' else 30)
        finally:self.close()
