"""Home Assistant projections of published evidence; a separate guard for the coarse register."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from mqtt_consumption import fresh_consumption


def field(parent, name):
    return "(" + parent + " or {}).get('" + name + "')"


def projected_sensors():
    """Stable suffix, display name, published topic and value expression."""
    root = 'value_json'
    periods = [('daily', 'Gas used today', 'daily_range', root),
               ('resumed', 'Gas since capture resumed', 'resumed_range', root),
               ('hour', 'Gas used last hour', 'recent_usage', field(root, 'hour'))]
    for index in range(4):
        quarters = "(value_json.get('quarters') or [])"
        quarter = f"({quarters}[{index}] if {quarters}|length > {index} else none)"
        periods.append((f'quarter_{index+1}', f'Gas last hour quarter {index+1}', 'recent_usage', quarter))
    periods.append(('resumed_photo', 'Photo-supported gas since capture resumed', 'resumed_range',
                    field(root, 'photo_supported')))
    for suffix, name, topic, parent in periods:
        for edge in ('lower', 'upper'):
            yield suffix+'_'+edge, name+' '+edge+' bound', topic, field(parent, edge)
    yield 'daily_low_use_estimate','Gas used today low-use estimate','daily_range',field(field(root,'low_use_estimate'),'value_ft3')


def check_register(path, key, obs):
    """Reserve the qualified value before MQTT. Repeating the same evidence is safe."""
    value = obs.get('register_ft3')
    if value is None:
        return 'register_ambiguous'
    event, digest = obs['event_id'], obs['source_sha256']
    seconds = datetime.fromisoformat(obs['captured_at']).timestamp()
    with closing(sqlite3.connect(path, timeout=1)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS confirmed (identity TEXT PRIMARY KEY, event INTEGER NOT NULL, '
                   'digest TEXT NOT NULL, seconds REAL NOT NULL, value INTEGER NOT NULL)')
        prior = db.execute('SELECT event,digest,seconds,value FROM confirmed WHERE identity=?',(key,)).fetchone()
        if prior:
            if prior == (event, digest, seconds, value):
                return None
            if event <= prior[0] or seconds <= prior[2]:
                return 'register_out_of_order'
            if value < prior[3]:
                return 'register_moved_backward'
            # Each accepted value represents a 100 ft³ bucket.
            if value - prior[3] >= 100 + (seconds-prior[2])*obs['maximum_rate_per_second']:
                return 'register_rate_exceeded'
        db.execute('INSERT OR REPLACE INTO confirmed VALUES(?,?,?,?,?)',(key,event,digest,seconds,value))
    return None


class GasSensors:
    def __init__(self, directory):
        self.checkpoint = Path(directory)/'mqtt-register.sqlite3'
        from nominal_register import AbsolutePublisher
        self.absolute = AbsolutePublisher(self.checkpoint)
        self.reset_connection()

    def reset_connection(self):
        self.absolute.sent = None
        self.configured = False
        self.last = None
        self.previous_point = None
        self.previous_result = {}

    def discover(self, output):
        def sensor(suffix, name, topic, expression, *, unit='ft³', kind=None, state=None,
                   diagnostic=False, domain='sensor', numeric=True, attributes=None, enabled=False):
            uid = output.config['unique_id']+'_'+suffix
            source = output.base+'/'+topic
            expiry = 660 if topic in ('daily_range','recent_usage','resumed_range') else max(90,output.interval*3)
            present = 'is_number(v) and v is not boolean and v|float >= 0' if numeric else 'v is not none'
            assign = '{% set v = '+expression+' %}'
            config = dict(name=name,unique_id=uid,device=output.config['device'],state_topic=source,
                          expire_after=expiry,availability_topic=source,enabled_by_default=enabled,
                          availability_template=assign+"{{ 'online' if "+present+" else 'offline' }}",
                          value_template=assign+"{{ v if "+present+" else none }}")
            if topic in ('daily_nominal', 'absolute_nominal'):
                del config['expire_after']
                del config['availability_topic']
                del config['availability_template']
                config['json_attributes_topic'] = source
            if topic == 'absolute_nominal':
                config['suggested_display_precision'] = 2
            if unit: config['unit_of_measurement']=unit
            if state: config['state_class']=state
            if kind: config['device_class']=kind
            if diagnostic: config['entity_category']='diagnostic'
            if attributes:
                config['json_attributes_topic']=source
                config['json_attributes_template']=attributes
            if source.endswith('/meter_diagnostics') and suffix in ('confirmed_register','status'):
                config['json_attributes_topic']=source
            output._publish('homeassistant/'+domain+'/'+uid+'/config',json.dumps(config),True)
        # Keep the estimate and its evidence on one entity for everyday use.
        sensor('daily_nominal', 'Gas used today nominal estimate', 'daily_nominal',
               field('value_json', 'value_ft3'), enabled=True)
        sensor('absolute_nominal', 'Gas meter reading', 'absolute_nominal',
               field('value_json', 'value_ft3'), kind='gas', state='total', enabled=True)
        for suffix,name,topic,expr in projected_sensors():
            section='value_json'
            if suffix.startswith('resumed_photo_'):
                section=field(section,'photo_supported')
            elif suffix.startswith('quarter_'):
                index=int(suffix.split('_')[1])-1
                section=f"(value_json.quarters[{index}] if (value_json.get('quarters') or [])|length > {index} else none)"
            assumption = ("(value_json.get('low_use_estimate') or {}).get('assumption')" if suffix=='daily_low_use_estimate'
                          else "section.get('assumption')")
            attrs=("{% set section = "+section+" or {} %}{% set end = section.get('through') or {} %}"
                   "{{ dict(measured_at=end.get('captured_at'), event_id=end.get('event_id'), "
                   "source_sha256=end.get('source_sha256'), assumption="+assumption+") | to_json }}")
            sensor(suffix,name,topic,expr,attributes=attrs)
        for suffix,name,unit,kind,state,diagnostic,numeric in (
            ('confirmed_register','Confirmed gas register (100 ft³ resolution)','ft³','gas','total',False,True),
            ('raw_reading','Raw gas meter estimate','ft³',None,None,True,True),
            ('delta','Gas change since previous reading','ft³',None,None,False,True),
            ('flow','Gas flow between readings','ft³/min','volume_flow_rate','measurement',False,True),
            ('timestamp','Gas reading time',None,'timestamp',None,True,False),
            ('status','Gas reading status',None,None,None,True,False)):
            sensor(suffix,name,'meter_diagnostics',field('value_json',suffix),unit=unit,kind=kind,
                   state=state,diagnostic=diagnostic,numeric=numeric)
        sensor('problem','Gas reading problem','meter_diagnostics',field('value_json','problem'),
               unit=None,kind='problem',diagnostic=True,domain='binary_sensor',numeric=False)
        self.configured = True

    def interval_values(self, snapshot, point):
        if not point:
            self.previous_point = None
            self.previous_result = {}
            return {}
        obs = snapshot['consumption'].get('event_observation') or {}
        if (not obs.get('clock_id') or not obs.get('context_id') or type(obs.get('monotonic_us')) != int
                or any(obs.get(k)!=point[k] for k in ('event_id','source_sha256','format_id','captured_at'))):
            self.previous_point = None
            self.previous_result = {}
            return {}
        identity = (point['segment_id'], point['format_id'], obs['context_id'], obs['clock_id'])
        current = (identity, point['event_id'], obs['monotonic_us'], point['value'],point['source_sha256'])
        prior = self.previous_point
        if prior == current:
            return self.previous_result
        result = {}
        if prior and identity == prior[0] and (current[1] <= prior[1] or current[2] <= prior[2] or current[3] < prior[3]):
            return {}
        if prior and identity==prior[0] and current[1]==prior[1]+1 and current[2]>prior[2]:
            seconds=(current[2]-prior[2])/1_000_000
            delta=current[3]-prior[3]
            if 0 <= delta <= point['maximum_rate_per_second']*seconds:
                result={'delta':delta,'flow':60*delta/seconds}
            else:
                return {}
        self.previous_point=current
        self.previous_result=result
        return result

    def publish(self, output, snapshot, obs):
        from mqtt_output import fresh_state
        if not self.configured:
            self.discover(output)
        age=max(90,output.interval*3)
        data={}
        if obs:
            try:
                reason=check_register(self.checkpoint,output.config['unique_id'],obs)
            except (sqlite3.Error,OSError):
                reason='register_checkpoint_unavailable'
            data.update(timestamp=obs['captured_at'],event_id=obs['event_id'],source_sha256=obs['source_sha256'])
            if reason:
                obs.pop('register_ft3',None)
                obs.pop('register_resolution_ft3',None)
            else:
                data['confirmed_register']=obs['register_ft3']
            data['status']=reason or obs['interpretation']
            data['problem']='ON' if reason else 'OFF'
        else:
            data.update(status='no_qualified_reading',problem='ON')
        try:
            self.absolute.publish(output, obs, snapshot)
        except (sqlite3.Error, OSError):
            data.update(status='absolute_checkpoint_unavailable', problem='ON')
        raw=snapshot.get('_raw_meter_reading')
        if raw:
            state=fresh_state({**snapshot,'reading':raw},age)
            if state and obs and state['format_id']==obs['format_id'] and state['value']>=0:
                data['raw_reading']=state['value']
        data.update(self.interval_values(snapshot, fresh_consumption(snapshot,age) if obs else None))
        payload=json.dumps(data,sort_keys=True,allow_nan=False)
        if self.last != payload:
            output._publish(output.base+'/meter_diagnostics',payload)
            self.last=payload
