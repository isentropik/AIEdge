"""Pure shared HA/CLI policy validation. No capture or publication permission."""
from reading_format import finite_number
FIELDS={'normal_interval_seconds','urgent_interval_seconds','full_refresh_seconds','phase_probe_budget','uncertainty_probe_width'}
def validate_policy(value,interval=None):
    if not isinstance(value,dict) or set(value)!=FIELDS:raise ValueError('event_policy_fields_invalid')
    if any(not finite_number(v) or v<=0 for v in value.values()):raise ValueError('event_policy_number_invalid')
    if value['urgent_interval_seconds']>value['normal_interval_seconds']:raise ValueError('event_policy_interval_invalid')
    if interval is not None and value['normal_interval_seconds']!=interval:raise ValueError('event_policy_fixed_interval_mismatch')
    return dict(value)
def final_two(document,reader):
    dials=document['dials']
    if len(dials)!=len(reader.dials) or any(type(d['index']) is not int for d in dials) or sorted(d['index'] for d in dials)!=list(range(len(reader.dials))):raise ValueError('event_dial_mapping')
    # FormatStore validates periods in physical coarse-to-fine order; indices
    # map that authoritative order to runtime calibration, never numeric order.
    return [d['index'] for d in dials[-2:]] if len(dials)>=2 else []
def validate_options(mode,policy,interval):
    if mode not in ('FULL','EVENT_LAST_TWO'):raise ValueError('recognition_mode_invalid')
    if policy or mode=='EVENT_LAST_TWO':validate_policy(policy,interval)
    elif not isinstance(policy,dict):raise ValueError('event_policy_fields_invalid')
def edit_allowed(recognition):
    if getattr(recognition,'observation_context',None):raise ValueError('event_selection_restart_required_choose_FULL_before_editing')
def partial_supported(reader,pair):
    runtime=getattr(reader,'runtime',None)
    return bool(pair and getattr(reader,'reuse_unchanged',False) is True and runtime is not None and getattr(runtime,'handle',None) and callable(getattr(runtime,'masked_function',None)) and callable(getattr(runtime,'prepare_masked',None)))
