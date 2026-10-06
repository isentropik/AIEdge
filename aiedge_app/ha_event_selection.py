"""Startup-only Supervisor opt-in. Recommendations never schedule captures."""
from event_mode import validate_policy,final_two,partial_supported
from event_selection_config import configure_document
def configure(options,store,recognition,formats,library):
    if options.get('recognition_mode','FULL')=='FULL':return recognition
    policy=validate_policy(options['event_selection_policy'],options['interval_seconds'])
    if not recognition or not recognition.reader or not formats or not formats.active:raise ValueError('event_selection_runtime_required')
    reader=recognition.reader;pair=final_two(formats.active[0],reader)
    support=partial_supported(reader,pair)
    caps={'minimum_interval_seconds':options['interval_seconds'],'partial_recognition':support}
    selected=configure_document({'schema_version':1,'format_id':formats.active[1],'configuration':policy,'capabilities':caps},store,recognition,formats,library)
    selected.ha_selection={'requested_mode':'EVENT_LAST_TWO','effective_mode':'EVENT_LAST_TWO' if support else 'EVENT_FULL_FALLBACK','partial_supported':support,'selected_indices':pair,'fixed_interval_seconds':options['interval_seconds'],'cadence_execution':'fixed','timing_capability_measured':False,'alignment_required':True,'edit_policy':'choose_FULL_and_restart_before_editing','policy':policy}
    return selected
def status(recognition,options=None):
    base=dict(getattr(recognition,'ha_selection',{'requested_mode':'FULL','effective_mode':'FULL','partial_supported':False,'cadence_execution':'fixed','alignment_required':True}))
    if getattr(recognition,'observation_context',None) and not hasattr(recognition,'ha_selection'):
        supported=recognition.capabilities['partial_recognition']
        base.update(requested_mode='EVENT_LAST_TWO',effective_mode='EVENT_LAST_TWO' if supported else 'EVENT_FULL_FALLBACK',partial_supported=supported)
    base.update(context_id=getattr(recognition,'observation_context',None),first_event=getattr(recognition,'observation_first_event',None),failure=getattr(recognition,'last_error',None) or base.get('failure'))
    if options:base['requested_mode']=options.get('recognition_mode','FULL');base['fixed_interval_seconds']=options.get('interval_seconds')
    if base['failure']:base['state']='blocked'
    else:base['state']='ready'
    if getattr(recognition,'observation_context',None):
        import sqlite3
        try:
            with recognition.lock,recognition.store.connect() as db:
                row=db.execute('SELECT event_id FROM event_recognition_requests WHERE pipeline=? AND context=? ORDER BY event_id DESC LIMIT 1',(recognition.reader.pipeline_id,recognition.observation_context)).fetchone()
                request=recognition._request(db,row[0]) if row else None
            if request:
                base['last_decision']={'observed':request['reader_observed'],'mode':request['recommendation']['requested_mode'],'reasons':request['full_reason'],'recommended_interval_seconds':request['recommendation']['supported_interval_seconds'],'execution':'recommendation_only','continuity_certified':False}
        except (ValueError,TypeError,KeyError,sqlite3.Error,OSError):base.update(state='blocked',failure='event_recognition_saved_state_unavailable')
    return base
