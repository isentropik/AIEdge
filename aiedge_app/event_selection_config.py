"""Explicit service opt-in; recommendations never enable capture or MQTT."""
from pathlib import Path
from saved_file import SavedFile
from event_recognition import EventRecognition,decode

def configure(path,store,recognition,formats,accounting_library):
    if not path:return recognition
    if not accounting_library or not store or not recognition or not recognition.reader or not formats or not formats.active:
        raise ValueError('event_selection_runtime_required')
    raw=SavedFile(Path(path)).read()
    if raw is None:raise ValueError('event_selection_configuration_missing')
    document=decode(raw.decode('utf-8'),32768)
    if not isinstance(document,dict) or set(document)!={'schema_version','format_id','configuration','capabilities'} or type(document['schema_version']) is not int or document['schema_version']!=1:
        raise ValueError('event_selection_configuration_invalid')
    physical,identity=formats.active
    if document['format_id']!=identity:raise ValueError('event_selection_format_mismatch')
    from accounting_native import AccountingNative
    try:
        native=AccountingNative(accounting_library)
        if not native.supports_masked:raise ValueError('accounting_mask_unsupported')
        tracker=native.tracker(physical);tracker.close()
    except (OSError,ValueError,AttributeError) as exc:
        raise ValueError('event_selection_accounting_unavailable') from exc
    candidate=EventRecognition(store,recognition.reader,physical,document['configuration'],document['capabilities'])
    # Startup has no running workers. Callers replace related references only
    # after construction succeeds, so a failed opt-in preserves the old reader.
    return candidate
