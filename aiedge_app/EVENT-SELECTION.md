# Development selection controller

The normal Home Assistant container command uses full recognition. For isolated
development, `service.py --event-selection-config /path/to/selection.json`
selects the event controller. Keep the usual native, accounting, model and data
arguments. This flag does not enable capture, MQTT or archiving. There is no UI
toggle or container-command change in this release.

The UTF-8 JSON document has exactly these fields:

```json
{
  "schema_version": 1,
  "format_id": "<current 64-character reading-format revision>",
  "configuration": {
    "normal_interval_seconds": 30,
    "urgent_interval_seconds": 10,
    "full_refresh_seconds": 300,
    "phase_probe_budget": 0.25,
    "uncertainty_probe_width": 0.3
  },
  "capabilities": {
    "minimum_interval_seconds": 10,
    "partial_recognition": true
  }
}
```

These numbers illustrate the schema; they are not validated physical settings.
The format must describe the actual dial periods, uncertainty and any defensible
maximum flow bound. Rates inferred from recent dial motion cannot certify that
whole turns were not missed. Optional capability acquisition/processing costs
raise the supported interval floor. Timing recommendations are recorded but
never reschedule the collector in this candidate.

The first new event, restart, changed acquisition context, missed deadline, stale
full anchor or uncertain accounting requests a full read. Other eligible events
request the last two physical dials, mapped to reader indices. Full alignment
and preprocessing run in either mode. Unknown upper positions stay absent;
partial observations withhold the absolute register. Relative accounting retains
its uncertainty and unresolved gaps rather than borrowing stale upper readings.

Requests, mask-specific image caches and event bindings are additive tables in
the existing capture database. The current format/pipeline/configuration define
a separate immutable context and accounting segment. Old inference rows, event
history and segments remain. A format or pipeline change requires constructing
a new controller; incompatible hot changes are withheld. Invalid opt-in files
stop inference, accounting, capture, MQTT and archive workers, while retaining
the HTTP diagnostics/setup interface.

Trial journals record exact event IDs in an opted-in context. Historical result
reads validate the original context/request/cache/acquisition without rerunning
the old policy or falling back to a full image-digest result. Identical JPEGs can
therefore have different full/partial results, and every event reaches accounting.
MQTT's existing equal-value suppression runs after accounting; suppressed output
does not discard capture history or certify a new physical measurement.

Back up the complete data volume before any approved installation or experiment.
Source fingerprints create a new relative segment even in ordinary full mode;
old cumulative history remains, and continuity across that gap is not inferred.
An app rollback restores software; restoring its complete data backup separately
restores the ledger snapshot and loses any newer events. A source-only rollback
does not restore databases or physical camera state.
