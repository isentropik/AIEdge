# Development status - October 5, 2026

Dev29 is a local candidate based on released dev28. It exposes explicit
Supervisor FULL-default/EVENT_LAST_TWO recognition options. Partial requests
follow the validated physical coarse-to-fine dial mapping and require a live
runtime profile, masked native export, exact-region reuse and compatible
accounting. Unsupported optimization uses full observations in the event ledger;
invalid selected configuration or durable evidence stays blocked.

Capture keeps its existing fixed schedule. Recognition mode does not enable
capture, MQTT, archiving or automatic updates. Alignment and quality checks
remain mandatory. Models, native code, dependencies, default accounting inputs
and output defaults are unchanged. Exact future compiled library identities
must still be verified before relying on default pipeline/segment continuity.

Selected-context edits require FULL and an app restart first. Mode/policy/context
changes retain prior data and start linked relative segments at the persisted
latest-event floor, with unresolved interpretation-change gaps. Completed event
bindings survive restart without repeated inference. Identical image data can
still represent separate acquisition events; numeric MQTT deduplication retains
freshness/reconnect and new-segment exceptions.

The isolated implementation passed 75 focused synthetic/unit/host-native checks
and six fake-DOM UI checks. An independent accounting lane passed nine new and
three existing targeted synthetic checks with no skips. They cover generic dial
counts, physical index order, direction normalization, carry/rollover, retained
uncertainty for whole-turn aliases and high-rate/long-gap cases, and durable
FULL-to-event-to-FULL transitions. The decision gap for rejected/inconsistent
feedback was reproduced and fixed conservatively for the next event.

These tests do not establish optical accuracy, model generality, measured capture
timing, a physical maximum rate or whole-turn continuity. Independent frozen
regression, rendered UI and exact-head Linux/package validation remain release
gates. Dev28's earlier merged-head Linux CI does not validate this new source.

Phase 2 remains open for independent recognition accuracy and physical cumulative
accounting. Camera firmware/recovery, sustained cadence, interrupted storage,
UI/setup and clean installation remain later phases. No camera reflash, live
update, opt-in or output enablement is authorized by this local candidate.
