"""Validated capture recommendations. This module performs no I/O or scheduling.

Measured phase speed is a probe heuristic, not a maximum-flow guarantee. Every
capture must still reach the durable accounting ledger before publication dedup.
"""
from reading_format import finite_number

def _number(value,name,positive=False):
    if not finite_number(value) or value<0 or (positive and value==0):raise ValueError('invalid_'+name)
    return value

def recommend(event,capabilities,configuration):
    if not all(isinstance(value,dict) for value in (event,capabilities,configuration)):
        raise ValueError('invalid_capture_policy_input')
    required={'normal_interval_seconds','urgent_interval_seconds','full_refresh_seconds','phase_probe_budget','uncertainty_probe_width'}
    if set(configuration)!=required:raise ValueError('invalid_capture_policy_configuration')
    for key in required:_number(configuration[key],key,positive=True)
    if configuration['urgent_interval_seconds']>configuration['normal_interval_seconds']:
        raise ValueError('urgent_interval_exceeds_normal')
    floor=_number(capabilities.get('minimum_interval_seconds'),'minimum_interval_seconds',positive=True)
    cost=sum(_number(capabilities.get(key,0),key) for key in ('acquisition_seconds','processing_seconds'))
    _number(cost,'combined_processing_cost')
    floor=max(floor,cost)
    partial=capabilities.get('partial_recognition')
    if type(partial) is not bool:raise ValueError('invalid_partial_recognition_capability')
    reasons=[];mode='LAST_TWO';uncertain=False
    for key in ('first','gap','restart','context_changed','quality_uncertain','pose_uncertain','phase_ambiguous','backpressure'):
        flag=event.get(key,False)
        if type(flag) is not bool:raise ValueError('invalid_'+key)
        if flag:reasons.append(key);mode='FULL';uncertain=True
    if not partial:reasons.append('partial_recognition_unsupported');mode='FULL';uncertain=True
    age=_number(event.get('full_age_seconds',0),'full_age_seconds')
    if age>=configuration['full_refresh_seconds']:reasons.append('periodic_full');mode='FULL'
    requested=configuration['normal_interval_seconds']
    speed=event.get('observed_phase_speed')
    if speed is not None:
        _number(speed,'observed_phase_speed')
        if speed>0:
            requested=min(requested,configuration['phase_probe_budget']/speed)
            reasons.append('observed_motion_probe')
    width=_number(event.get('phase_interval_width',0),'phase_interval_width')
    if width>=configuration['uncertainty_probe_width']:
        reasons.append('phase_uncertainty');mode='FULL';uncertain=True
    if uncertain:requested=min(requested,configuration['urgent_interval_seconds'])
    if requested<floor:
        reasons.append('requested_cadence_not_supported');mode='FULL';uncertain=True
    return {'requested_mode':mode,'requested_interval_seconds':requested,
            'supported_interval_seconds':max(floor,requested),'reasons':reasons,
            'continuity_certified':False,'uncertainty_retained':uncertain,
            'accounting_before_publication_required':True,'history_event_required':True,
            'physical_scalar':None,'alignment_bypass':False,
            'execution':'recommendation_only','rate_basis':'observed_phase_speed_is_not_a_maximum_rate'}
