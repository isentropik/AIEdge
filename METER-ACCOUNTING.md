# Meter accounting implementation and remaining work

The portable algorithm is `MeterAccounting.h`, with Python reference
`needle_reader_v2/meter_interval.py` in the parent workspace. The Python reference
uses the existing `cumulative_check.reconstruct` and `sequence_check.check`; the
C++ implementation ports those calculations. The existing read-only shadow trial
still makes no consumption claims and its held-out images remain untouched.

## Units and interval candidates

- Secondary: 5 ft³/revolution, therefore 0.5 ft³ per 0–10 dial unit.
- Last main dial: 1,000 ft³/revolution, therefore 100 ft³ per numbered step.
- 20 secondary revolutions equal one last-main numbered step; 200 equal a full
  last-main revolution. Higher main dials carry in decades.
- Monotonicity is checked on reconstructed cubic feet, not raw individual dials.
  Individual 9.9 → 0.0 transitions are normal. A whole-register rollover is
  flagged as possible rollover/reset, not silently assumed to be forward use.

Given two normalized secondary positions, every candidate interval is:

`0.5 * (current - previous) + 5 * integer_turn_offset` ft³.

The algorithm intersects candidate uncertainty intervals with the main-register
change interval, nonnegative physical consumption, and an optional supplied
maximum physical flow multiplied by actual elapsed capture time. It never chooses
the nearest integer turn merely because it is closest to a main estimate.

There is **no default maximum flow assumption**. Even identical secondary
positions can conceal whole revolutions. Short cadence alone is not proof that
less than one turn elapsed. With the current 0.1-dial-unit assumed main error,
the main difference has about ±20 ft³ uncertainty and commonly permits several
secondary turns. The default 0.1-unit tolerances are explicit algorithm inputs,
not empirical maximum-error guarantees or confidence probabilities. Real operation
needs justified bounds and validation, not just passing synthetic tests.

Outcomes are invalid input, review required, ambiguous turn count, within noise,
bounded interval only, or an estimate under the supplied bounds. Raw readings and
negative jitter remain unchanged. Noise and ambiguous intervals have no point
consumption or flow estimate. Bounds remain available where supported. The
1e-7-ft³ numerical allowance only handles floating-point arithmetic at a
10-million-ft³ register magnitude; it is separate from dial-reading uncertainty.

## Capture provenance

The firmware capture path now attaches the camera driver's timestamp of the first
DMA buffer to the image and carries it into the alignment wrapper. This is
microseconds since boot, not HTTP retrieval time, decode completion, or UTC.
Demo images and invalid/future driver timestamps are not valid timing evidence.
Failed capture/decode or incompatible image sizes stop the normal flow before
recognition/publication, with `Capture failed` status and no automatic reboot for
that failure. Insufficient target buffers are rejected before image clearing/copy.

The interval API requires valid increasing capture timestamps and a matching,
nonzero clock-domain identity. Different boot uptimes cannot be compared after
restart merely because both numbers are positive. The polar observer now assigns
a boot-local random 64-bit identity. A persisted/UTC bridge remains work;
this random identity alone does not provide restart continuity.

## Evidence

`needle_reader_v2/test_meter_interval.py` checks physical ratio/carry/jitter cases
and 2,500 C++/Python differential cases, including 1,000 zero-error mathematical
fixtures at large register magnitudes. These tests found and then fixed roundoff
rejections; they do not measure real-image accuracy. Camera tests compile the
actual capture function with driver/decode/clock stubs and cover 11 success/failure
cases. Controller tests verify capture failure stops downstream processing.

## Still required

`MeterCheckpoint.h` defines the initial reference checkpoint codec: versioned
229-byte records containing model/calibration SHA-256 identities, six original
positions, driver timestamp and clock identity, error/rate assumptions, and
CRC32. Integer and IEEE binary64 fields are explicitly little endian. Decode
requires exact identities/assumptions and valid frame semantics before replacing
the caller's output. CRC detects accidental corruption, not malicious editing.
The codec alone is not proof of SD-card power-loss recovery.
`test_meter_checkpoint.py` passes exact
round trips, all 1,832 single-bit corruptions, all 229 truncated prefixes, extra
bytes, identity/bound changes, and malformed semantics with a recomputed CRC.

`MeterCheckpointStore.h` now provides two-slot storage through the existing
storage interface. Each slot has a generation and outer CRC. Writes target the
older/missing slot and require exact readback; they never overwrite the current
newest valid slot. Partial new records can recover the remaining reference with
an explicit `RecoveredOlder` status. Read errors, contradictory equal-generation
records, generation exhaustion and an incompatible newest intact record block
writing. No corrupt evidence is deleted. A first-ever interrupted write with no
valid prior copy remains corrupt rather than inventing a baseline. Tests inject
all 249 partial-record lengths and verify the previous reference survives.

`MeterRecovery.h` now connects the storage interface to session restoration and
saving. Initialization rejects mismatched active assumptions. A restored reference
forces the first usable observation to establish an explicit restart baseline,
even if its boot identity matches by coincidence. Invalid intervening observations
do not clear that restart requirement. It refuses to replace an already active
session and disables further writes after an uncertain save instead of retrying.
Tests cover restore, first post-restore baseline, saving the new reference,
assumption conflict and suppression of automatic retries after a partial write.

The opt-in polar observer now initializes the coordinator before its first
observation/rejection and saves accepted references using `ConfigStorage::Files`
at `/sdcard/config/polar-meter-reference.0` and `.1`. Rejected observations do
not save a new reference. `PolarIdentity.h` is generated with the frozen geometry;
its identities cover the verified model and exact generated geometry/marker
header (the checkpoint's calibration identity). Host integration uses an
in-memory storage stub and confirms both slots are saved.
This does not prove physical SD/FAT power-loss behavior: both files can be lost if the
filesystem or card loses unrelated metadata. It also does not bridge elapsed
time across reboot, resolve missing revolutions, or restore a cumulative total.

The portable `MeterSession.h` now retains a usable reference across rejected
images. Invalid or contradictory frames clear the exposed interval estimate,
without replacing that reference. The next usable frame is compared over the
full timestamp gap. Duplicate/out-of-order timestamps do not advance it. A new
nonzero clock identity starts a new baseline with an explicit restart state;
no across-boot consumption is inferred. Ambiguous intervals remain ambiguous.
`referenceCaptureUs` identifies the latest retained frame and `intervalStartUs`
identifies the start of the reported interval. These are deliberately separate.

`test_meter_session.py` passes rollover, rejected-frame gap, duplicate time,
backward total, restart, unresolved turns and invalid-bound checks. This session
layer is now wired into `doPolarNetwork` through `PolarAccounting.h`. All six
successful inference results and their driver's capture timestamp are observed
together; polar preprocessing/model/inference failures reject the current
observation while preserving its reference. Debug logging exposes session and
interval status names. A locked snapshot accessor supports future HTTP readers;
the controller processing guard serializes writers. Host flow tests exercise
rejection, baseline, ambiguous intervals and retention using stub inference.

Reference persistence does not sum positive changes, restore cumulative consumption, or
prove physical reading accuracy. Capture/alignment failures before the polar
stage do not create a rejected observer event yet. Starting a full cycle clears
an existing observer estimate into `awaiting_reading`; early failures therefore
cannot leave the previous estimate presented as the current interval. It may
remain awaiting a reading after an early failure; consult cycle timing/status.

Authenticated GET `/meter_accounting` now returns a locked snapshot with readable
state/reason, reference and interval-start monotonic timestamps, candidate count,
bounds, and nullable consumption/flow estimates. Nonfinite values serialize as
JSON null. `verified_accuracy:false` is explicit; `reference_persisted` and
`persistence_state` separately report verified storage state. This is
diagnostic output under assumed bounds, not a verified billing total. It includes
the raw five main positions and secondary position on their normalized 0–10
scale, capture time validity and boot identity (a JSON string to preserve all
64 bits). Rejected observations retain their supplied raw positions; pending
runs and recognition failures without readings expose no raw observation.
Assumed main/secondary error bounds and optional maximum flow are explicit,
separate from observed values. None is an empirically verified error guarantee.
UI and MQTT integration remain work. Session serializer tests parse
estimated, pending, ambiguous and invalid outputs as JSON and check nulls.

1. Wire interval results and meaningful reason names into the opt-in polar flow,
   HTTP/MQTT status and frontend; keep estimates separate from verified values.
2. Implement persisted state with model/calibration/version identity, atomic
   recovery, clock provenance and explicit gaps. Never bridge an ambiguous gap by
   inventing a turn or silently summing main and secondary totals.
3. Extend the same-boot cumulative segment below with persisted segment identity
   and explicit discontinuities. Adding only positive noisy interval estimates
   would fabricate usage and is not acceptable.
4. Reconcile continuous secondary changes against the main register without
   double-counting and without converting linked estimates into training labels.
5. Validate device timestamps, cadence, real error/rate assumptions and restart
   behavior before publishing live physical quantities. No live units/totals,
   configuration or firmware have been changed by this local work.

## Fixed-reference cumulative segment (September 22)

`MeterCumulative.h` now compares accepted endpoints with the first usable image
of the current boot segment. It never adds positive adjacent estimates. That
preserves small movements that individually fall within noise and prevents
stationary jitter from ratcheting the total upward on each frame. The physical
main-register and secondary-wheel constraints are the same as interval accounting;
ambiguous whole turns remain ambiguous. The lower bound cannot decrease. An
endpoint whose upper bound contradicts that lower bound is rejected, as is an
endpoint inconsistent with the original anchor even if it passes its adjacent
comparison. A point estimate below the established lower bound is withheld.

`/meter_accounting` includes `cumulative_since_anchor`, with anchor/through
timestamps, bounds, nullable estimate, status, freshness and `persisted:false`.
Pending/rejected readings retain the last accepted bounds with `current:false`
and clear the point estimate. A reboot or restored reference starts a new
segment; the outage is not silently bridged. This is not yet a lifetime total
or a persistent Home Assistant consumption entity. Point estimates can vary
within the uncertainty interval and must not be fed into a monotonic total sensor.

`test_meter_cumulative.py` passes 2,000 stationary jitter frames, 500 small
increments totaling 10 ft³, a gap spanning 20 secondary rotations (100 ft³),
freshness, restart, ambiguous turns and anchor contradiction. Session, checkpoint
and actual polar-flow host regressions also pass. Error bounds remain assumptions,
not empirical guarantees; no new training labels or accuracy claims result.


## Restart-gap endpoint evidence

Session status now retains the last usable reading before a restart and the
first usable reading afterward in restart_gap, each with its own boot identity
and capture timestamp. It remains visible as subsequent same-boot readings
proceed or await new data. elapsed_seconds and estimated_ft3 remain null and
resolved=false. The Restarted state also exposes its clock-domain-mismatch reason.
This is diagnostic evidence, not a consumption estimate or durable gap ledger:
persisted=false is explicit, and only the latest gap is retained in RAM. A later
reboot may lose that diagnostic pair; persisted cumulative segments remain work.

Session tests cover direct boot changes and checkpoint reference restoration,
retention across subsequent/pending readings, and no invented duration/delta.
Checkpoint corruption/torn-write and cumulative jitter/turn regressions pass.
No model labels, physical units, live totals or device configuration changed.


## Version 2 cumulative checkpoint

New saved references include the same-boot cumulative anchor and established
lower bound in MTRC0002 (301 bytes; 321-byte two-slot envelope). Maximum bound,
estimate and status are recomputed from the saved endpoints and unchanged error
assumptions rather than trusted independently. Validation rejects cross-clock
anchors, inverted timestamps, inconsistent positions, nonfinite/contradictory
bounds and wrong model/calibration. Legacy MTRC0001 references remain readable.
The two-slot store accepts either length and still refuses fallback past an
intact incompatible newest record. Torn writes preserve the older verified slot.

Recovery exposes the saved result as previous_segment with its old boot identity,
current=false, persisted=true and included_in_current_segment=false. The first
new reading starts a separate anchor, retaining the unresolved restart endpoints.
Current-segment persisted reflects verified checkpoint status. Nothing sums the
previous segment and gap into a lifetime total. This retains only the latest
saved segment, not a durable multi-segment history; closing/summing a complete
history and resolving permissible gaps are still outstanding.

Tests pass 4,240 single-bit corruptions, 530 truncated prefixes and 570 partial
slot writes across both formats, nonzero segment recovery/JSON separation,
legacy reference restoration, and semantic rejection. Session and actual polar
flow regressions pass. Old firmware does not understand the v2 envelope length;
a rollback can recover only a remaining v1 slot or reject storage, so deployment
must preserve checkpoint copies and review that compatibility limitation. No live
checkpoint or firmware was changed; physical SD power-loss recovery is untested.


## Completed-segment retention before checkpoint rotation

Recovery now retains a loaded v2 segment in memory until the first new checkpoint
save. Before rotating an active slot it writes and verifies a separate record
named polar-meter-reference.segment-BOOT-ANCHOR-END.bin in the same trusted
configuration directory. That record is the validated v2 checkpoint itself,
including identities, bounds and endpoint positions. Matching existing bytes are
accepted idempotently; different bytes are a conflict and never overwritten.
Read/write/readback failure disables further saves for this boot. A partial
archive is retained for inspection while the prior active checkpoint stays intact.

Tests cover all 301 partial archive lengths, no automatic retry after uncertainty,
identical and conflicting existing records, and preservation after two subsequent
active-slot rotations. Existing codec, torn-slot and polar-flow regressions pass.
This is single-owner storage, not protection from external edits or a transactional
multi-process writer. There is no automatic deletion or retention cap yet; storage
exhaustion is reported as a persistence failure. A segment history reader and gap
reconciliation are still required before producing a lifetime total. Physical SD
power-loss/fsync behavior remains untested; no live storage was changed.


## Validated segment-history aggregation

MeterHistory.h decodes up to 64 completed-segment records using the production
checkpoint validator and explicit model/calibration/error assumptions. It rejects
incompatible or corrupt records rather than omitting them from a claimed total.
Records with the same boot/anchor are counted once, keeping the latest consistent
endpoint. Conflicting duplicate endpoints, decreasing lower bounds, contradictory
progression and overlapping different anchors are rejected. Shared endpoints must
have identical raw readings. Input ordering does not provide chronology across
boots; boot IDs are not timestamps.

The result exposes only covered-segment lower/upper consumption bounds and always
lifetimeComplete=false. It does not infer gaps, sum point estimates, or claim that
all history was supplied. Host tests cover ordering, duplicates, later endpoints,
overlap, shared endpoints, corrupt bytes, identity mismatch and bounded input.
This library is not yet connected to device directory enumeration or a history
endpoint; that integration must maintain bounded memory/IO and explicit omissions.
No physical accuracy or SD claims follow, and no live data was changed.


## Bounded completed-segment filesystem reader

MeterHistoryFiles.h reads the exact immutable record filenames under a trusted
firmware-selected directory. Each must be a regular 301-byte v2 record whose
boot/anchor/end fields match its filename and whose CRC, model, calibration and
bounds pass the production decoder. Reads are capped at 302 bytes to catch a
concurrent size change. A scan examines at most 512 directory entries and accepts
at most 64 records; limits, read failures and invalid records invalidate the
summary rather than silently omitting data. Caller must own processing/storage
access. This reader assumes trusted paths and does not protect against external
filesystem mutation or symlinks into other trusted files.

Real temporary-filesystem host tests cover valid records, unrelated files,
truncation/oversize, corruption, mismatched names, directory instead of file,
missing directory, scan cap and 65 valid records exceeding the history cap.
The history API/task still needs runtime integration; reads must not block HTTP
or run concurrently with checkpoint mutation. Output covers completed records
only and cannot be presented as a complete lifetime total. No SD/device data was
read or written; physical filesystem and latency behavior remain unverified.


## Asynchronous history diagnostic endpoints

POST /meter_history (empty body/query) now queues an 8 KiB-stack background scan;
GET /meter_history returns its snapshot. Both use the existing basic-auth filter.
A second scan receives 409; task creation failure returns 503. Starting a scan
clears the old result. The worker acquires ProcessingAccess then UpdateAccess and
returns a busy result rather than waiting. Filesystem work uses fixed config
paths and compiled model/calibration identities, outside the HTTP handler.

Status carries scanned_at_uptime_us (scan completion, not image capture time),
completed_segments_only scope, validity/reason, deduplicated count and nullable
covered bounds. lifetime_complete and verified_accuracy remain false. This is an
on-demand snapshot; it does not auto-refresh or include the active checkpoint.
Two URI slots were added. Actual worker/handler host tests cover scheduling,
content rejection, contention, lock ownership, cleared stale results and JSON.
Actual filesystem tests cover file decoding separately. Device stack/heap, scan
latency and SD timing remain unverified; no live endpoint was accessed/deployed.


## Optional MQTT accounting snapshot

`PublishAccountingStatus = true` in [MQTT] opts into the separate topic
`<configured main topic>/accounting/status`. It defaults to false and has not been
set on the live meter. Payload schema meter-accounting-v1 wraps the same production
statusJson snapshot as /meter_accounting, plus published_at_uptime_us and the
current accounting boot identity (a string). Publication time is not capture time.
The snapshot carries raw capture time and boot identity; consumers must compare
those fields and state/current flags rather than assume every message is a new
observation. Pending, rejected or older segment data can appear in a snapshot.

Messages use existing QoS 1 enqueue behavior and retain=false regardless of the
legacy retain setting. No old-topic units/values/discovery configuration are
changed; no new HA entity or billing total is created. Null ambiguous consumption
and flow remain null; fields name ft3 and ft3_per_second explicitly. No conversion
to an existing main/secondary entity's configured unit is performed.

The snapshot is emitted when the normal pipeline reaches MQTT. Earlier pipeline
failures may prevent a fresh message, so consumers require their own freshness
handling; absence of a retained message does not guarantee UI expiry. Broker
acknowledgment/end-to-end HA delivery is not proven by a successful enqueue.
The topic does not replace the HTTP failure/status path.

Actual publication-body host tests verify default-off behavior, the precise
opt-in topic/envelope, nonretained QoS 1, null preservation, disconnected handling
and failure propagation. Serializer semantics are covered by separate accounting
tests. No broker or device was contacted. Config parser accepts TRUE case
insensitively; other values keep the option disabled. The field is available in the MQTT configuration editor as Publish accounting
status, default disabled. Its tooltip explains nonretained diagnostic semantics.


Configuration editor checks use the production JavaScript parser and serializer.
Enabled, disabled and commented accounting values survive round trips without
changing the legacy retain option. An absent accounting option defaults to false.
The section loop now handles end-of-file and reordered known sections instead of
skipping headings or reading past the final line. Short and reordered input fixtures
pass. Tooltips/configuration HTML were regenerated locally. Browser rendering and
live save remain unverified; no actual configuration file was changed.


### Optional maximum flow setting

On the test build, Meter and units offers an optional maximum in ft³/hour.
Leave it disabled unless a reliable physical maximum is known. An observed
average is not an upper bound. Setting the limit too low can reject readings or
select an incorrect turn count. Display-unit selection does not change this field.

Saving requires the current revision and an idle processing/storage boundary.
The response distinguishes saved-and-active from saved-but-not-active. Reload
after an uncertain save rather than retrying automatically. Each effective limit
has separate checkpoint/history files. Switching starts a new baseline; switching
back retains old records but cannot infer consumption during the gap.
See [validation and remaining limits](docs/FLOW-ASSUMPTIONS-STATUS.md).
