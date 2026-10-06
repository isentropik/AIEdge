"""Explicit service opt-in; recommendations never enable capture or MQTT."""
from pathlib import Path
from saved_file import SavedFile
from event_recognition import EventRecognition,decode

def configure(path,store,recognition,formats,accounting_library):
    if not path:return recognition
    raw=SavedFile(Path(path)).read()
    if raw is None:raise ValueError('event_selection_configuration_missing')
    return configure_document(decode(raw.decode('utf-8'),32768),store,recognition,formats,accounting_library)

def configure_document(document,store,recognition,formats,accounting_library):
    if not accounting_library or not store or not recognition or not recognition.reader or not formats or not formats.active:
        raise ValueError('event_selection_runtime_required')
    if not isinstance(document,dict) or set(document)!={'schema_version','format_id','configuration','capabilities'} or type(document['schema_version']) is not int or document['schema_version']!=1:
        raise ValueError('event_selection_configuration_invalid')
    physical,identity=formats.active
    if document['format_id']!=identity:raise ValueError('event_selection_format_mismatch')
    from event_mode import validate_policy,final_two,partial_supported
    validate_policy(document['configuration']);pair=final_two(physical,recognition.reader)
    capabilities=decode(__import__('json').dumps(document['capabilities']))
    if not isinstance(capabilities,dict) or set(capabilities)-{'minimum_interval_seconds','partial_recognition','acquisition_seconds','processing_seconds'}:raise ValueError('event_capability_fields_invalid')
    from wheel_capture_policy import recommend
    recommend({'first':True},capabilities,document['configuration'])
    reader=recognition.reader
    runtime_support=partial_supported(reader,pair)
    capabilities['partial_recognition']=capabilities['partial_recognition'] and runtime_support
    from accounting_native import AccountingNative
    try:
        native=AccountingNative(accounting_library)
        if not native.supports_masked:raise ValueError('accounting_mask_unsupported')
        tracker=native.tracker(physical);tracker.close()
    except (OSError,ValueError,AttributeError) as exc:
        raise ValueError('event_selection_accounting_unavailable') from exc
    candidate=EventRecognition(store,recognition.reader,physical,document['configuration'],capabilities)
    # Startup has no running workers. Callers replace related references only
    # after construction succeeds, so a failed opt-in preserves the old reader.
    return candidate
