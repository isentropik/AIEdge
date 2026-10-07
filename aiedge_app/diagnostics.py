"""Deliberately limited support report: no images, readings or credentials."""
import importlib.metadata,platform,sqlite3
from datetime import datetime,timezone

PACKAGES=('ai-edge-litert','numpy','Pillow','paho-mqtt')

def selection_diagnostics(recognition):
    """Bounded typed projection; operational error text never leaves this report."""
    from ha_event_selection import status
    from reading_format import finite_number
    import re
    result={'current_failure':bool(getattr(recognition,'last_error',None))}
    try:raw=status(recognition)
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError,AttributeError):
        return dict(result,state='blocked',current_failure=True)
    if not isinstance(raw,dict):return dict(result,state='blocked',current_failure=True)
    result['current_failure']=result['current_failure'] or bool(raw.get('failure'))
    enums={'requested_mode':{'FULL','EVENT_LAST_TWO'},'effective_mode':{'FULL','EVENT_LAST_TWO','EVENT_FULL_FALLBACK','BLOCKED'},'state':{'ready','blocked'},'cadence_execution':{'fixed'},'edit_policy':{'choose_FULL_and_restart_before_editing'}}
    for key,allowed in enums.items():
        if isinstance(raw.get(key),str) and raw[key] in allowed:result[key]=raw[key]
    for key in ('partial_supported','timing_capability_measured','alignment_required'):
        if type(raw.get(key)) is bool:result[key]=raw[key]
    value=raw.get('fixed_interval_seconds')
    if finite_number(value) and 10<=value<=3600:result['fixed_interval_seconds']=value
    value=raw.get('context_id')
    if isinstance(value,str) and re.fullmatch('[a-f0-9]{64}',value):result['context_id']=value
    value=raw.get('first_event')
    if type(value) is int and 1<=value<=9223372036854775807:result['first_event']=value
    indices=raw.get('selected_indices')
    if isinstance(indices,list) and len(indices)<=2 and all(type(i) is int and 0<=i<32 for i in indices) and len(set(indices))==len(indices):result['selected_indices']=list(indices)
    from event_mode import validate_policy
    try:result['policy']=validate_policy(raw['policy'])
    except (ValueError,TypeError,KeyError):pass
    decision=raw.get('last_decision')
    if isinstance(decision,dict):
        projected={}
        if decision.get('mode') in ('FULL','LAST_TWO'):projected['mode']=decision['mode']
        observed=decision.get('observed')
        if isinstance(observed,list) and 1<=len(observed)<=16 and all(type(v) is bool for v in observed):projected['observed']=list(observed)
        allowed={'first','gap','restart','context_changed','quality_uncertain','pose_uncertain','phase_ambiguous','backpressure','partial_recognition_unsupported','periodic_full','observed_motion_probe','phase_uncertainty','requested_cadence_not_supported','missed_prior_recommendation_deadline','fine_observation_uncertain','full_refresh_uncertain','observation_only_unbounded_accounting'}
        reasons=decision.get('reasons')
        if isinstance(reasons,list) and len(reasons)<=32:projected['reasons']=[v for v in reasons if isinstance(v,str) and v in allowed]
        interval=decision.get('recommended_interval_seconds')
        if finite_number(interval) and interval>0:projected['recommended_interval_seconds']=interval
        projected.update(execution='recommendation_only',continuity_certified=False)
        result['last_decision']=projected
    return result

def build(store,collector=None,recognition=None,setup=None,reading_format=None,mqtt_output=None,configuration=None,consumption=None,archive=None):
    report={'schema_version':1,'generated_at':datetime.now(timezone.utc).isoformat(),
            'runtime':{'python':platform.python_version(),'system':platform.system(),'architecture':platform.machine()},
            'dependencies':{},'configuration_valid':not configuration or configuration.get('state')=='ready',
            'capture':{'enabled':collector is not None,'interval_seconds':collector.interval if collector else None,
                       'missed_slots':collector.missed_slots if collector else None,'current_failure':bool(collector and collector.last_error)},
            'storage':{'state':'unavailable'},'recognition':{'configured':False},
            'calibration':{'available':setup is not None},'number_format':{'available':reading_format is not None},
            'mqtt':{'enabled':mqtt_output is not None},
            'omitted':['credentials','camera_address','images','dial_positions','human_reviews','meter_values','frame_identifiers','environment_variables','local_paths']}
    for name in PACKAGES:
        try:report['dependencies'][name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:report['dependencies'][name]=None
    from camera_status import STATES
    snapshot=getattr(collector,'camera_state',{}) if collector else {}
    state=snapshot.get('state','not_checked')
    report['camera']={'state':state if state in STATES|{'not_checked','checking','unavailable'} else 'unknown'}
    mode=snapshot.get('mode')
    if mode in ('remote-camera','full-reader'):report['camera']['mode']=mode
    for key in ('camera_available','settings_ready','clock_synchronized'):
        if type(snapshot.get(key)) is bool:report['camera'][key]=snapshot[key]
    if store:
        try:
            status=store.status()
            report['storage']={key:status['storage'].get(key) for key in ('state','free_bytes','reserve_bytes')}
            report['capture'].update({key:status.get(key) for key in ('captures','unique_images','duplicate_images','failures')})
            report['capture']['timing']=store.capture_timing()
        except (OSError,sqlite3.Error):pass
    if recognition:
        with recognition.lock:
            reader=recognition.reader
            report['recognition']['configured']=reader is not None
            report['recognition']['current_failure']=recognition.last_error is not None
            if reader:
                report['recognition']['dial_count']=len(reader.dials)
                report['recognition']['pipeline_id']=reader.pipeline_id
    for key,component in (('calibration',setup),('number_format',reading_format)):
        if component:
            state=component.status()
            report[key]['recovery_required']=bool(state.get('recovery'))
            report[key]['saved']=state.get('calibration' if key=='calibration' else 'format') is not None
    if mqtt_output:
        state=mqtt_output.status().get('state')
        report['mqtt']['state']=state if state in ('starting','connected','publishing','waiting_for_format','waiting_for_reading','disconnected','error') else 'unknown'
    report['consumption']={'configured':consumption is not None}
    if consumption:
        state=consumption.status().get('state')
        report['consumption']['state']=state if state in ('not_configured','unavailable','waiting_for_image','recovering','pending','anchored','estimated','within_noise','bounded','ambiguous') else 'unknown'
        report['consumption']['current_failure']=consumption.last_error is not None
    report['archive']={'state':'unavailable'}
    if archive:
        try:
            state=archive.status()
            report['archive']={key:state[key] for key in ('state','copied_events','pending_events','error','in_progress')}
        except (OSError,sqlite3.Error):pass
    report['performance']=store.performance.snapshot() if store and hasattr(store,'performance') else {'state':'unavailable'}
    report['event_selection']=selection_diagnostics(recognition)
    return report
