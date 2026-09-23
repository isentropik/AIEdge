# Cycle timing (local implementation, not deployed)

Full `ClassFlowControll::doFlow` calls now acquire a single-cycle guard. A
concurrent full-cycle call returns false immediately rather than queueing work.
The same non-waiting processing guard now covers controller manual stages,
capture-only calls and configuration initialization. Busy initialization returns
without invalidating the running configuration or rewriting its status. This
does not make legacy initialization a transactional hot reload, nor protect
every HTTP reader of flow objects. Those paths still require review.

Authenticated GET `/cycle_timing` reports boot-local monotonic microseconds:

- Full-cycle attempts, completions, failures and rejected overlapping calls.
- Cycles taking more than 30 seconds, including failed cycles.
- The last finished cycle's start/end, up to 16 stage attempts with duration and
  result, and the total number of stage attempts (including retries).
- The camera driver's capture timestamp and interval from the preceding observed
  capture. Missing, future and pre-cycle timestamps are not accepted. Failed
  recognition after a valid capture still contributes to capture cadence.
- `valid_readings: null`: pipeline completion is not verified reading validity.

While a cycle is active, `last` remains the preceding finished cycle. Zero capture
timestamps/intervals mean absent evidence, not zero-time capture. Counters reset
on reboot. A reset during a cycle loses that unfinished cycle; this is not a
persistent crash log. Stage indices refer to the configured flow order. Full
duration includes controller status/publication work; individual stage timing
covers each stage call only.

The configured scheduling interval remains unchanged. Automatic scheduling now
preserves a monotonic start-slot cadence, skipping elapsed slots after overruns
instead of immediately starting back-to-back catch-up runs. Exact equality with
the next slot allows an immediate run. Explicit early manual wakeups establish
a new cadence from that run. Delays round up to OS ticks. Invalid arithmetic
stops automatic scheduling with an error instead of creating a tight loop.
`missed_schedule_slots` counts elapsed start slots, not failed recognition or
all absent captures (for example a rejected busy run is counted elsewhere).

For a 30-second configured interval, a 35-second cycle skips the slot at second
30 and next runs at second 60. The actual camera capture can lag the scheduled
run start; use the capture timestamp telemetry to measure actual cadence.
The 30-second duration threshold is a target, not a demonstrated capability.
Interval distributions, valid reading rate, device runtime, and complete
configuration activation remain work.

Verification: `needle_reader_v2/test_cycle_telemetry.py` in the parent workspace
tests the real header and HTTP serializer with host clock, mutex and HTTP stubs:
32 concurrent rejections, bounded retry records, destructor failure accounting,
timestamp rejection, capture intervals, threshold boundary and JSON output.
`test_firmware_controller_failure.py` verifies actual controller failure paths
with stage and telemetry stubs, plus actual manual entry-point exclusion.
Startup tests check that a busy initializer leaves readiness and status intact.
`test_cycle_schedule.py` checks 10,015 integer reference cases, including exact
deadlines, overruns, invalid inputs and signed 64-bit overflow boundaries.
The ESP32 build passed; neither test is hardware
performance or reading-accuracy evidence.

## Accepted-reader cycle counter

`accepted_reader_cycles` counts completed pipelines with a valid capture timestamp
and a successful frozen PolarV1 analog stage. `last.reader_accepted` reports that
stage evidence even if a later stage failed; the completed counter does not count
such failed pipelines. Plain completion or an absent/invalid capture timestamp
cannot count as an accepted-reader cycle. This measures software acceptance, not
independent physical reading accuracy, postprocessing truth or broker receipt.
`valid_readings` remains null. Tests cover accepted completion, accepted-but-aborted
cycles and completion without capture evidence. Controller regressions also pass.


## Offline trial analysis

`needle_reader_v2/analyze_cycle_trial.py INPUT --output NEW_REPORT` consumes
ordered saved `/cycle_timing` snapshots wrapped as `{"snapshots": [...]}`. The
endpoint now includes a 128-bit random lowercase-hex `boot_id`, initialized once
per firmware process. It is an observation epoch, not an authentication token.
All samples must have the same valid identity; mixed/missing identities are
rejected. For legacy samples only, `same_boot_verified: true` remains an explicit
external assertion and cannot override mismatching identifiers. Never assert it
merely because counters look increasing. No device polling or configuration
changes occur in this tool. A future collector must preserve boot identity and
request latency before claiming a complete performance trial.

Counter deltas expose failed/accepted cycles, rejected overlap attempts, deadlines
and skipped schedule slots. Per-cycle distributions deduplicate repeated polls and
report unobserved records explicitly. Accepted capture-to-pipeline-finish duration
is separate from whole-cycle duration and capture cadence. Failed/unaccepted cycles
are not included in accepted timing but remain in the acceptance denominator.
The first snapshot is a counter baseline; its last cycle can contribute to observed
distributions, which therefore describe observed records rather than precisely the
counter-delta window. Capture intervals can also start before that baseline.

Reader acceptance is not verified reading accuracy or MQTT receipt. Missing cycle
records can bias percentiles. No automated target-achieved claim is emitted, and
no duration is subtracted across boots. Eight host tests cover boot identity, duplicate/active
polls, missing failures, counter regression, inconsistent records, percentiles and
the real serialized endpoint fixture. Device performance remains unmeasured.


## Read-only trial collector

`needle_reader_v2/collect_cycle_trial.py --origin http://DEVICE --output NEW_FOLDER`
collects 60 samples at 10-second intervals by default. It only GETs /cycle_timing;
no stream, image capture, settings write or reboot is requested. Optional Basic
credentials come from METER_TRIAL_USER and METER_TRIAL_PASSWORD environment
variables, never URL arguments or output logs. Redirects and ambient proxies are
not followed. Use HTTPS when supported; Basic credentials over plain HTTP have
no transport confidentiality.

Raw bounded responses, SHA-256 hashes, retrieval UTC, request durations and failures
are preserved. Requests use a socket inactivity timeout, not a hard total deadline
against a trickling server. At most 720 requests, 64 KiB plus one detection byte
per response; intervals must be 5..60 seconds. Three consecutive errors stop the
trial. Overdue poll slots are skipped without catch-up bursts. Existing output
folders are rejected. This tool has not been run against the live meter.

Valid snapshots are separated by firmware boot_id. Each boot is analyzed separately;
missing/invalid boot IDs and malformed responses remain failures, while counter
regression within a boot invalidates its summary. Reports do not claim reading
accuracy, broker receipt or target achievement. Six injected-transport tests cover
raw preservation, boot separation, consecutive failure stop, missed polls, size
limits, credentials omitted from logs, endpoint scope and overwrite protection.
Actual device-network responsiveness still requires an approved hardware trial.


## Device diagnostics page

System > Meter Diagnostics opens meter_diagnostics.html. It makes no initial or
periodic requests. Refresh status sequentially reads cycle timing, image archive
status and cached completed-segment history. Scan saved history separately POSTs
the read-only scan job, then reads current status; it does not trigger recognition,
change configuration or automatically retry a scan. A running scan requires a
later manual refresh. Requests have a five-second AbortController deadline, use
same-origin credentials and reject redirects. Buttons share an in-flight guard.

The page distinguishes software acceptance from physical accuracy and excludes
active segments/unresolved gaps from any lifetime claim. Unavailable fields show
Unknown. Failed refreshes replace each affected section's previous text; uncertain
scan outcomes instruct a status refresh before retry. Values use textContent.
Node tests cover formatter fallbacks, fixed request scope, no initial polling,
HTTP/network errors, duplicate actions and markup treated as text. Browser visual
verification remains outstanding; the previous local-preview policy refusal was
not bypassed. No page or firmware was deployed; candidate j predates this UI.
