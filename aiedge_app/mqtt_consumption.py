"""Publish durable segment-relative consumption, never infer an omitted value."""
import math,re
from datetime import datetime,timezone
from reading_format import validate

MODES=('reading','consumption','gas_consumption')

def finite(value):
    try:return type(value) in (int,float) and math.isfinite(value)
    except OverflowError:return False

def configuration(identity,document,interval,mode,reading_discovery):
    if mode not in MODES:raise ValueError('invalid_mqtt_output_mode')
    topic,base,cfg=reading_discovery(identity,document,interval)
    if mode=='reading':return topic,base,cfg
    validate(document)
    if mode=='gas_consumption' and document['unit'] not in ('ft3','m3','L'):
        raise ValueError('mqtt_gas_unit_invalid')
    unique=cfg['unique_id']+'_'+mode
    base+='/'+mode
    cfg.update(name='Observed gas consumption' if mode=='gas_consumption' else 'Observed consumption',
               unique_id=unique,state_topic=base+'/state',json_attributes_topic=base+'/attributes',
               availability_topic=base+'/availability',state_class='total',
               last_reset_value_template='{{ value_json.last_reset }}')
    if mode=='gas_consumption':cfg['device_class']='gas'
    return 'homeassistant/sensor/'+unique+'/config',base,cfg

def _fresh_observation(snapshot,max_age,clock,states):
    doc=snapshot.get('format');c=snapshot.get('consumption');frame=snapshot.get('latest')
    if not isinstance(doc,dict) or not isinstance(c,dict) or not isinstance(frame,dict):return None
    try:_,revision=validate(doc)
    except (ValueError,TypeError,KeyError):return None
    # An explicit rate assumption is required; cadence alone cannot rule out turns.
    rate=doc.get('maximum_rate_per_second')
    if not finite(rate) or rate<=0:return None
    if c.get('state') not in states or c.get('observation_accepted') is not True:return None
    event=snapshot.get('_timing_event_id')
    if type(event) is not int or event<1 or type(c.get('event_id')) is not int or c['event_id']!=event:return None
    segment=c.get('segment_id')
    if not isinstance(segment,str) or not re.fullmatch('[a-f0-9]{32}',segment):return None
    if segment!=snapshot.get('_publication_segment_id') or c.get('format_id')!=revision or c.get('unit')!=doc['unit']:return None
    digest=frame.get('sha256')
    if not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest) or c.get('source_sha256')!=digest:return None
    if c.get('through_captured_at')!=frame.get('captured_at'):return None
    value,lo,hi=c.get('value'),c.get('minimum'),c.get('maximum')
    if not all(finite(x) for x in (lo,hi)) or not 0<=lo<=hi or c.get('upper_unbounded') is not False:return None
    try:
        captured=datetime.fromisoformat(frame['captured_at'].replace('Z','+00:00'))
        anchor=datetime.fromisoformat(c['anchor_captured_at'].replace('Z','+00:00'))
        if captured.tzinfo is None or anchor.tzinfo is None or anchor>captured:return None
        if not 0<=((clock or datetime.now(timezone.utc))-captured).total_seconds()<=max_age:return None
    except (ValueError,TypeError,KeyError,AttributeError):return None
    if c['state']=='anchored' and (value!=0 or lo!=0 or hi!=0 or anchor!=captured):return None
    # A gap belongs to the segment boundary. Publish no invented bridging delta.
    return dict(value=value,last_reset=anchor.astimezone(timezone.utc).isoformat(),
                captured_at=frame['captured_at'],source_sha256=digest,format_id=revision,
                segment_id=segment,event_id=event,minimum=lo,maximum=hi,
                maximum_rate_per_second=rate,unresolved_gap=c.get('unresolved_gap'),
                coverage='observed_segment_only',accuracy_verified=False)

def fresh_consumption(snapshot,max_age,clock=None):
    obs=_fresh_observation(snapshot,max_age,clock,('anchored','estimated'))
    if obs and finite(obs['value']) and obs['minimum']<=obs['value']<=obs['maximum']:
        return obs

def _register_hundreds(absolute, register_limit):
    """Return the absolute register truncated to 100 ft³ only if every candidate agrees."""
    if not isinstance(absolute,dict) or absolute.get('unit')!='ft3':
        return None
    if absolute.get('provenance')!='temporal_consumption_bounds':
        return None
    bounds=absolute.get('bounds')
    if not isinstance(bounds,dict) or bounds.get('state')!='bounded' or bounds.get('wraps_register') is not False:
        return None
    ranges=bounds.get('ranges')
    if not isinstance(ranges,list) or not 1<=len(ranges)<=256:
        return None
    bucket=None
    for band in ranges:
        if not isinstance(band,dict):
            return None
        lo,hi=band.get('lower'),band.get('upper')
        if not finite(lo) or not finite(hi) or not 0<=lo<=hi<register_limit:
            return None
        hundreds=int(lo)//100
        if int(hi)//100!=hundreds or (bucket is not None and hundreds!=bucket):
            return None
        bucket=hundreds
    return bucket*100

def fresh_range(snapshot,max_age,clock=None):
    """Report the outer limits of the current segment, including disjoint possibilities."""
    from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
    obs=_fresh_observation(snapshot,max_age,clock,('bounded','ambiguous','within_noise','estimated','anchored'))
    if obs is None:return None
    obs.pop('value')
    obs['segment_started_at']=obs.pop('last_reset')
    unit=snapshot['consumption']['unit']
    if unit=='ft3':
        register=_register_hundreds(snapshot['consumption'].get('absolute'),snapshot['format']['dials'][0]['value_per_revolution'])
        if register is not None:
            obs['register_ft3']=register
            obs['register_resolution_ft3']=100
    lower=(Decimal(str(obs['minimum']))*100).to_integral_value(rounding=ROUND_FLOOR)/100
    upper=(Decimal(str(obs['maximum']))*100).to_integral_value(rounding=ROUND_CEILING)/100
    symbol={'ft3':'ft³','m3':'m³'}.get(unit,unit)
    obs['label']=f"{lower:.2f}–{upper:.2f} {symbol}"
    obs['interpretation']=snapshot['consumption']['state']
    return obs
