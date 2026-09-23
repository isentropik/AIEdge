# OTA development status

The user requested OTA updates as part of the custom firmware objective.
The inherited partition layout contains two 1,900 KiB application slots, and
the inherited updater writes the inactive slot using ESP-IDF OTA APIs.
Automatic bootloader/application rollback is currently disabled in sdkconfig.
The inherited boot diagnostic returned true unconditionally; the early-boot
follow-up below removes that false acceptance. Rollback is not thereby verified.
The installed device bootloader has not been inspected or changed in this work.
An application OTA alone cannot be assumed to enable bootloader rollback.

The local file-to-OTA transaction now rejects missing/conflicting partitions,
missing/undersized/oversized images, file positioning/read/close errors, rejected
flash writes, failed image validation and failed boot-slot selection. It aborts
unfinished handles and closes opened files. ESP-IDF documents that ota_end
consumes its handle even on failure, so it is not subsequently aborted.
The previous-invalid-version guard remains, but returns failure instead of
hanging. A failed descriptor read is not used as initialized version data.
The source file's measured size must match the bytes written. Each chunk yields.

`test_ota_transaction.py` runs the actual transaction body against 19 local
partition/file/flash scenarios. It verifies cleanup and that boot selection
occurs only after validation. It does not write physical flash or establish
power-loss recovery. A boot selection error has an uncertain physical outcome;
do not blindly retry it.

Remaining work includes meaningful startup health checks, supported bootloader
migration and rollback policy, update task/HTTP admission and failure reporting,
bundle identity and firmware/model/web compatibility, interrupted SD asset
updates, exact recovery artifacts and an approved hardware trial. The current
development ZIP is not an upstream-compatible OTA installation bundle.
No device update, configuration change or reboot has occurred.

Startup worker follow-up: BIN and ZIP firmware-write failures now return without
calling reboot. The worker releases its local buffers before self-deletion and
signals startup to continue. Task creation failure also returns rather than
entering the wait loop. Three actual-worker fault cases pass in host tests,
alongside the 19 transaction cases. These tests do not validate RTOS scheduling.
ZIP extraction/HTML replacement still precedes firmware validation and is not
transactional; continuing old firmware after a failed ZIP may leave incompatible
web assets. That remains a deployment blocker, not a rollback guarantee.

ZIP extraction follow-up: names no longer serve as printf format strings or
overflow a fixed 64-byte filename buffer. Relative path validation rejects
absolute paths, traversal components, backslashes, colons and control bytes.
The OTA extractor checks file metadata/open/write/close failures, releases its
archive and heap buffers on failure, and returns ERROR even if firmware was
extracted before the failing entry. The startup worker refuses ERROR/missing
firmware before activating HTML. Reopening the archive releases the prior
reader, and skipped initial-config payloads no longer leak their buffers.
Actual-body tests inject failures after the firmware entry and pass. This does
not yet provide all-entry preflight, duplicate-name checks, expansion limits,
staging of every asset or transactional activation. Existing destinations may
still be changed by earlier entries before a later failure.

Archive preflight now checks all entry metadata before extraction, using the
same opened archive. It rejects unsupported/encrypted entries, case-insensitive
duplicate paths, file/directory prefix conflicts and FAT trailing-dot/space
aliases. Engineering limits are 512 entries, 200 ASCII characters per path,
2 MiB per expanded file and 32 MiB total. These bound the current updater; they
are not hardware memory guarantees or user-requested limits. Tests cover those
boundaries and verify that a later invalid name causes zero file renames.

The user clarified that a replacement need not be a direct fork. Future update
design may replace this legacy ZIP workflow completely. Keep the validated reader
and hardware interfaces where useful; do not preserve risky inherited update
behavior merely for compatibility. A versioned bundle with separate staging,
verification, activation and recovery is the intended direction. Existing
preflight does not substitute for that transaction or its hardware validation.

## Verified local staging prototype

`needle_reader_v2/stage_firmware_bundle.py` validates the development bundle's
exact manifest inventory, per-file lengths/SHA-256, model identity, path safety,
case-insensitive conflicts and expansion limits before creating a new staging
directory. It rereads and verifies each ZIP member while writing, verifies staged
file readback, then writes STAGED.json and renames the completed pending directory.
Failed pending directories are preserved. Existing destinations are refused.
No active firmware, model or web files are changed by this tool.

The September 22 candidate f staged 125 verified files locally. Tests cover
valid staging/readback, refusal to overwrite, corrupt content, extra entries,
unsafe paths, name conflicts, invalid metadata and model identity mismatch.
This is host-side preparation, not an implemented device OTA transaction.
The manifest hashes provide integrity against accidental corruption, not a
publisher signature. The marker and rename are not a power-loss durability
proof; flash activation, device-side staging, boot/asset compatibility and
recovery still need implementation and hardware validation. Do not feed this
bundle to the inherited legacy updater.

Staging write follow-up: every file and the final marker now require a full write,
flush, fsync and exact readback before publication. The reserved STAGED.json name
cannot be supplied by a bundle. Tests inject each of five file-sync failures and
final rename failure; no destination is published, and pending evidence remains.
The staging test is now included in the candidate packaging checks. Filesystem
and directory-entry power-loss durability, external concurrent mutations and
device-side activation remain outside these host tests. Candidate f predates
these staging-tool changes; its firmware bytes are not changed by them.

## Early boot false acceptance removed

`CheckOTAUpdate` runs before PSRAM and camera/reader initialization. It now only
observes running-image identity and OTA state, handles missing partitions/hash
errors/unsupported rollback explicitly, and logs pending verification without
marking an image valid. The unconditional diagnostic and duplicated acceptance
block were removed. It does not automatically trigger rollback from this early
observation. A compatible bootloader retains its pending-image restart policy.

Six actual-body host cases pass, along with the 19 OTA transaction regressions.
A post-initialization reader/hardware health decision is still required; pending
images are deliberately not accepted by this incomplete health workflow. Do not
enable rollback or deploy this as a finished OTA recovery solution. Candidate f
predates this firmware change and is stale relative to the worktree.

## Health evidence endpoint

Authenticated GET `/ota_health` reports current system error flags, configuration
readability, the frozen six-vector self-test result, and whether the last inactive
capture pipeline completed with a capture timestamp. These are observations, not
an atomic acceptance decision or proof of real-image accuracy. Configuration
changes may invalidate older evidence; no boot acceptance uses this endpoint.
Bundle compatibility and rollback verification remain explicitly false, as do
acceptance readiness and acceptance-by-request. It performs no OTA writes.

Seven actual-handler host scenarios passed, plus the existing asynchronous model
diagnostic regression. The endpoint exposes missing evidence for the future
post-initialization gate; it does not implement that gate or authorize flashing.

## Compact device compatibility contract

Future candidate packages include `device-manifest.json` in `meter-bundle-v1`
format. It binds the ESP32 firmware file length/hash, app-image digest, frozen
model identity and exact runtime web/model/diagnostic assets. `bundle_id` hashes
the canonical contract before that ID is added. This is not a digital signature
or deployment authorization. Validation checks unsigned classic ESP32 image
segment boundaries, XOR checksum, padding and appended SHA-256; ESP-IDF still
must validate load addresses, revision compatibility and flash writes.

The whole firmware file SHA differs from the app-image SHA returned for image
identity; both are explicit. Tests exercised corrupt/truncated images, changed
assets, wrong model identities and the current compiled binary. The device-side
manifest parser and asset selection/activation remain unfinished. Existing
candidate f predates this contract and must not be treated as compatible.

## Device manifest parser

`DeviceBundleManifest.h` validates the compact contract with bounded input,
limited nesting, exact known fields, integer lengths, SHA identities, allowed
runtime namespaces, archive expansion/path-conflict limits, required assets and
model hash agreement. It reconstructs the Python canonical contract and checks
the supplied bundle ID through an injected hash function. 813 host cases test
parsing, rejection and exact canonical bytes against the Python generator; the
hash oracle in this cross-language test is substituted. Production hash binding,
reading staged assets, per-file verification and device activation are not yet
connected. The parser alone must not be treated as update readiness.

## Streamed staged-artifact verification

`VerifyDeviceBundle.h` reads a bounded manifest, verifies its identity with the
provided SHA implementation and expected bundle ID, then hashes the declared
firmware and every runtime asset in 4 KiB chunks. It checks regular-file type,
exact lengths, EOF/read errors and close results. The parsed manifest is returned
only when all declared artifacts match. It performs no file writes or activation.
24 temporary-filesystem host cases pass with real mbedTLS SHA-256, covering good
content, wrong IDs and missing/truncated/extended/corrupt artifacts, with no-write
assertions. This connects the parser to real hashing but is not yet called by the
live updater. The caller must own the trusted staging tree exclusively throughout
verification and use; concurrent mutation and untrusted symlinks are not solved
by hash checks. Extra undeclared files are not enumerated by this verifier and
must never be selected as runtime assets. SDK firmware validation is still needed.


## Immutable runtime asset routing (local development)

`BundleSelection.h` binds a fully verified staged tree to the running app digest
and frozen model digest. Its first load attempt is final for that instance;
failed selection cannot silently fall back to legacy assets. `RuntimeBundle.h`
provides a shared boot-only selection object. The application-keyed boot
integration described below now initializes it before normal service startup.

The common HTTP file sender (including flow-state preview images), frozen model
initialization/inference and runtime diagnostic fixtures now use that resolver.
Compressed HTTP alternatives are resolved independently through the manifest:
an undeclared `.gz` file cannot replace a declared web asset. Mutable config,
logs and captured images retain their existing paths. Tests cover missing assets,
traversal paths, app/model mismatches, one-shot selection and mutable-path routing
using the actual verifier with real SHA and temporary files. Actual reader and
runtime-runner regression tests pass with explicit legacy resolver stubs; those
tests do not establish selected-bundle HTTP behavior or hardware correctness.

The ESP32 build passed (`bundle-routing-build-fixed.log`, 25.99 seconds).
Remaining: boot-time selection metadata, startup folder/version checks, staged
installation, exclusive ownership during use, complete HTTP routing tests and
health-gated rollback acceptance. The inherited updater must not be used for the
new bundle flow. No firmware or assets have been installed on the meter.


## Application-keyed boot selection

Boot now reads `/sdcard/bundles/apps/<running-app-sha256>.id` before SoftAP,
normal web service, asset checks and processing. The index is exactly 64 lowercase
hex bytes, optionally followed by LF. It selects the immutable tree under
`/sdcard/bundles/objects/<bundle-id>`. The complete manifest and artifacts must
verify against both the running app digest and compiled frozen model identity.
No boot-time file rename, index write or firmware acceptance is performed.

Development/bootstrap builds permit a missing index, retaining legacy paths.
Managed OTA builds must define `METER_REQUIRE_BUNDLE`; missing or malformed
indexes then reject startup. Malformed/unreadable indexes reject even in bootstrap
mode. Selection is sealed after the first attempt. Packaging does not yet enforce
managed mode: current development candidates are NOT an approved update route.
Installation must durably write verified objects and the per-app index before
switching boot partitions and retain old objects/indexes for rollback.

Startup folder checks and web version reads use the same selected assets. The
processing-start branch now permits only the complete allowed noncritical mask;
a time-sync warning cannot bypass a simultaneous critical bundle/folder failure.
124 actual branch combinations pass. Nineteen real-filesystem boot selection
cases pass, alongside 24 artifact verification cases, with no write assertions.
Verification buffers moved to checked heap allocations because the configured
main task stack is 3584 bytes. Remaining actual stack/heap margin, boot timing,
SD fault recovery and power-loss durability require target validation.

Remaining implementation includes managed packaging, installation/activation,
write protection while selected assets are in use, and health-gated acceptance.
No device configuration or firmware was deployed.

Clean ESP32 build verified after these changes: `bundle-boot-clean-build.log`,
187.96 seconds, firmware uses 1,622,652 of 1,945,600 application bytes (83.4%).
This verifies compilation/linking, not target runtime or OTA durability.


## Bundle index publication and flash transaction boundary

`InstallBundleIndex.h` verifies all artifacts in an already-staged object tree,
rejects the running application's identity and mismatched model, and publishes a
new per-app index using exclusive pending-file creation, exact write, fsync,
close and readback before rename/readback. Existing mappings are never replaced;
an identical mapping is returned as Existing only after artifacts reverify.
Failures retain pending files. Eight host cases exercise current-app/model
rejection, real writes/flush/readback, injected flush failure, retained pending
conflict, conflicting index, idempotence and subsequently damaged assets.
The Windows host flush wrapper uses `_commit`; production uses `fsync`.

The actual flash transaction now accepts a preparation callback after successful
`esp_ota_end` and closing the input file, before `esp_ota_set_boot_partition`.
Twenty-one host transaction cases pass, including callback refusal and success.
These tests model flash; they do not prove physical recovery. Existing callers
pass no callback, so managed bundle installation is NOT wired to an endpoint yet.
The upcoming managed caller must bind the actual flashed partition digest to
the manifest and invoke index publication under exclusive storage ownership.

This is not complete activation: extraction into immutable object directories,
managed build policy, authenticated installation route, write protection,
rollback acceptance and actual SD/power-loss testing remain. Rename safety
requires the documented exclusive ownership; fsync/readback alone does not
prove SD directory durability. No live device or server writes were made.


## Managed coordinator connected to the flash transaction

`ManagedBundleTransaction.h` now performs pre-flash verification and calls the
flash adapter with a post-validation callback. The adapter in `server_ota.cpp`
reads the actual target partition app SHA through ESP-IDF. Only an exact manifest
match permits index publication; only Installed/Existing permits boot selection.
The coordinator holds processing then camera access, and uses the fixed bundles
root. It does not reboot, accept the new image or change the current asset view.
It is not registered as an HTTP handler and is not invoked by legacy update paths.

Seven coordinator cases combine real SHA/filesystem verification and index
publication with simulated flash: current-app rejection, write/validation failure,
flashed-digest mismatch, conflicting mapping, boot-selection failure after index
publication, successful retry and damaged assets. Twenty-one underlying SDK-stub
transaction cases still pass. Actual ESP flash behavior remains untested.

Exclusive protection of the bundle tree against generic file endpoints and
concurrent updater calls is still a prerequisite before exposing this coordinator.
Managed packaging/build policy, authenticated staging/installation, durable SD
recovery and health-gated rollback acceptance remain incomplete. The current
policy permits only the compiled frozen model identity, not arbitrary new models.


## Generic file mutation protection and flash serialization

`BundleWritePolicy.h` rejects generic mutations of the FAT case-insensitive
bundles namespace and ambiguous paths (dot segments, separators, percent escapes,
short-name aliases, control/non-ASCII bytes and trailing dot/space). Upload,
single/bulk deletion and legacy ZIP extraction paths apply this restriction.
The alternate HTML extractor also checks its complete destination. Ordinary
config, logs, HTML and firmware staging files remain writable through existing
routes. Twenty-six actual policy cases pass; the actual ZIP extraction harness
also rejects a mixed-case bundle entry before any rename/extraction side effects.
This protects the reviewed routes, not physical SD edits or unreviewed plugins.

`UpdateAccess.h` serializes all calls to the low-level flash transaction. A busy
second caller fails before opening its firmware file or touching flash. The
actual transaction harness checks this and still passes its 21 failure/success
cases. The guard spans the post-flash bundle callback and boot selection. It is
not a cross-filesystem/physical lock and does not authorize an update.

Managed staging/API, build policy, update health acceptance and target validation
remain unfinished. No live device changes were made.


## Managed build policy and v2 manifest

`esp32cam-managed` inherits the esp32cam build flags and uses the same SDK
configuration, adding `METER_REQUIRE_BUNDLE`. Its boot path has no missing-index
legacy fallback. The default esp32cam environment remains bootstrap/development.
`package_firmware_trial.py --managed` selects the managed environment and rejects
an output with the wrong compiled boot-policy log marker. This is a build check,
not cryptographic authenticity or deployment authorization.

The device contract is now `meter-bundle-v2`, with explicit `boot_policy` bound
into its canonical hash. Only `required_bundle` candidates enter the managed
flash transaction; valid `optional_bundle` candidates are rejected before flash.
Python/C++ parser agreement passes 848 cases; managed transaction fixtures now
include a fully verified bootstrap bundle rejected with zero flash calls. Existing
v1 candidates must be regenerated; they are intentionally not accepted by v2.

Pre-build manifest tests no longer depend on an old binary surviving a clean or
environment-switch build. Packaging explicitly reruns the binary-format test
after compilation with `METER_TEST_IMAGE`, then constructs/validates the manifest.
No full new package or live deployment is claimed by these source changes.


## Device-side managed staging

`StageDeviceBundle.h` preflights the archive's path inventory and expansion
limits, reads a bounded v2 device manifest, requires managed boot policy and the
frozen model, and checks required runtime entries before making staging folders.
It extracts only the manifest/firmware/runtime assets; documentation and host
validation logs in the development ZIP are not installed as runtime data.
Streaming callbacks enforce monotonic offsets, declared length, exact writes and
SHA. Each file is fsynced, closed and independently rehashed. The complete tree
is verified again before rename to `objects/<bundle-id>`. Existing objects are
verified and reused, never overwritten. Failed pending directories are retained.
No app index, active HTML, flash or boot partition is changed by staging.

Thirteen actual miniz/real-filesystem host cases pass, covering valid/repeated
staging, ignored nonruntime docs, wrong ID, failed flush and retained pending
conflict, traversal/case/prefix conflicts, corrupted assets, missing entries,
bootstrap policy, oversized entries and truncated ZIP. Production uses fsync and
POSIX mkdir; the Windows harness maps these to real `_commit`/`_mkdir` calls.
These tests do not establish physical SD power-loss durability or ESP memory use.

`stageManagedBundle` compiles in the OTA component, guarded by UpdateAccess.
Ordinary upload/delete requests now acquire that same guard and return 503 when
busy, preventing them from changing an input ZIP during managed staging/flash.
It is not yet exposed as an HTTP endpoint; a worker/API and explicit install UI
are still required. The managed ESP32 build passes (`managed-staging-build.log`,
22.98 seconds). No live server/device writes or firmware deployment occurred.


## Asynchronous staging HTTP interface

Authenticated `POST /bundle_stage` accepts exactly 64 lowercase hex body bytes
(the expected bundle ID), no query, and `X-Meter-Bundle-Action: stage`. It refuses
operation unless HTTP Basic authentication is configured, even though inherited
endpoints otherwise allow disabled authentication. The request is additionally
wrapped in the existing authentication filter. The custom header requires a
non-simple browser request; the new endpoints do not enable cross-origin access.

The fixed input is `/sdcard/firmware/managed-bundle.zip`, uploaded separately.
A worker with a bounded 24 KiB task stack performs staging; HTTP receives 202,
409 if a staging job is active, or 503 if task creation fails. Authenticated
`GET /bundle_status` reports active state, bundle ID and explicit outcome with
no-store caching. Status always reports installed=false: no install, flash,
boot-selection, image-acceptance or reboot action is exposed by these endpoints.
Two additional URI slots were reserved; registration failures are logged.

Tests execute the actual handlers/worker with HTTP/scheduler stubs and cover
missing auth configuration, malformed/incomplete requests, active job, task
creation failure, and all five staging results. ZIP/filesystem behavior remains
covered separately by the real miniz harness. Target task stack/heap, real auth
transport, staging responsiveness and actual SD behavior remain unverified.
The inherited auth logger now records header receipt without credential contents.

Remaining: browser UI, managed install endpoint plus health/rollback acceptance,
complete packaged-candidate validation and physical recovery/runtime trials.
No live endpoint or device was modified.


## Post-update health policy and cycle evidence

The local OtaHealthPolicy evaluates independent software prerequisites: rollback
configuration, pending image state, verified bundle, no system faults, readable
configuration, frozen model self-test, inactive processing, at least three
consecutive completed reader-accepted cycles, ordered monotonic capture timing,
and a latest capture no older than 180 seconds. Twenty-five production-header
host cases cover these vetoes and boundaries. This policy is not yet wired to
SDK image acceptance; the existing health endpoint remains read-only and reports
acceptance_ready=false. No physical rollback or reading-accuracy claim follows.

Cycle telemetry now exposes accepted_reader_streak. Aborted/failed cycles and
completed cycles without an accepted reader reset it. Host tests verify three
successive cycles, reset behavior, and the actual HTTP JSON field; the seven
existing health-endpoint snapshots still pass. Packaging runs the new policy
test. Candidate h predates these changes and is not an updated deployment bundle.

The earlier browser-UI pending note is superseded by managed_update.html/js and
candidate h's local upload/staging tests. Browser rendering remains unverified
because the preview tool refused the local URL; no alternate route was attempted.
Managed installation and health acceptance, actual rollback support, physical
recovery, and device performance remain incomplete. No live writes were made.


## Health report connected to boot evidence

Version 2 of /ota_health observes esp_ota_get_running_partition and the SDK image
state query, the immutable boot bundle selection, actual self-test snapshot,
configuration readability, faults, and cycle telemetry. It exposes
software_policy_ready/reason, rollback_configured, image_state_known,
pending_image and consecutive_reader_cycles. Unknown SDK state cannot count as
a pending image; legacy/rejected bundles cannot count as verified assets.

Twenty-eight actual-handler host cases cover both rollback build configurations
and individual missing/stale evidence, in addition to the 25 policy cases.
acceptance_ready, rollback_verified and image_accepted_by_this_request remain
false. The endpoint does not hold a transaction lock or invoke SDK acceptance;
its observational snapshots must not be reused as a mutation authorization.
Installed bootloader rollback and hardware recovery remain unverified. No live
meter/server changes were made. Candidate h does not include this work.


## Guarded acceptance operation

acceptHealthyManagedImage now acquires ProcessingAccess then UpdateAccess before
collecting fresh health evidence. Only a ready policy followed by a fresh SDK
PENDING_VERIFY check may invoke mark_app_valid_cancel_rollback. Success additionally
requires the same running partition and a VALID readback. Write errors and
uncertain readbacks return distinct outcomes; this operation never retries or
reboots. Twelve actual-operation host cases exercise both busy locks, health
rejection, missing/changed SDK state, write/readback faults, success and a repeated
call. The production lock implementations are used; SDK flash calls are stubbed.
Twenty-eight health-report snapshots also prove GET requests make zero writes.

No boot or HTTP caller invokes acceptance yet. Lifecycle scheduling, failure
policy, installed bootloader support and hardware recovery are still outstanding.
The operation is implementation work, not permission for a live acceptance/flash.


## Pending-image lifecycle integration

The automatic-flow task calls servicePendingImage after initialization and between
normal cycles. Only a rollback-configured, SDK-pending image enters validation.
It reserves the existing self-test state, runs frozen vectors on the flow task
before acceptance, then waits for the health policy's three consecutive accepted
reader cycles. Busy locks defer to a later cycle; a failed self-test or non-busy
acceptance result is terminal for this boot. SDK write/readback failures are not
retried. A 10-minute window is checked at service boundaries; expiry logs failure
and leaves the image unaccepted. This is not an independent watchdog and cannot
interrupt a hung cycle. No forced reboot or invalidation is performed. With
Autostart disabled there is only the initial service call and no automatic
acceptance; an eventual explicit maintenance path remains to be designed.

Ten actual-service host scenarios cover nonpending/nonrollback boots, ordered
self-test/reading acceptance, self-test failure, contention, uncertain readback,
window expiry and bad configuration/system faults. Tests use platform stubs and
verify the two call sites; they do not establish hardware timing or recovery.
Current SDK configuration still disables rollback. Before deployment, establish
and test the bootloader/configuration/recovery path rather than enabling that
flag as a substitute for physical evidence. No live changes were made.


## Managed installation HTTP worker

POST /bundle_install now requires configured basic authentication (and the
existing auth filter), X-Meter-Bundle-Action: install, no query, and the exact
64-byte identity of the last successful staging job. Stage/install share one
job reservation. Installation runs on the worker through installManagedBundle,
which re-verifies the immutable bundle, writes inactive flash and publishes its
asset index before selecting the next boot partition. No reboot is requested.

Status distinguishes boot_selected_reboot_required from install_failed_or_uncertain.
boot_selected records successful completion of the install API; installed remains
false because the new image has not booted or passed health validation. A failure
may have changed inactive flash/index/boot metadata and must not imply rollback
or no changes. There is no automatic retry; restaging is required before another
explicit attempt. Once selection succeeds, further jobs are rejected this boot.
Job status is in RAM and is not a durable installation journal.

Actual-handler host tests cover auth, malformed/partial input, shared contention,
staged identity, worker creation, failed install, required restaging, success and
selected-boot lockout. Flash is stubbed here; transaction coverage is separate.
The browser still offers staging only. Add explicit install/status UI, reconcile
boot selection via SDK readback and validate interrupted installs on hardware
before deployment. URI capacity is increased by one. No live writes were made.


## Install UI and boot-selection readback

The OTA transaction now reads the selected boot partition after the SDK selection
write and requires matching target address and size before returning success.
Missing/wrong readbacks return failure without a second write. Twenty-four actual
transaction host cases pass, including the three new readback failures. An error
can still mean metadata changed; it is not proof of no mutation.

The managed-update page now has a separate Install verified bundle button.
Its client freshly reads status, requires the matching successfully staged ID,
then sends the explicit install POST. It does not request reboot. Uploads are
blocked if boot is already selected. Status explains pending reboot and uncertain
install failure; automatic mutation retries remain absent. Twenty-four client
workflow tests pass, including mismatched IDs, active jobs, uncertain failure and
install transport error. These are mocked transport tests, not browser rendering
or device network tests. The earlier preview refusal remains unresolved; no
alternate route was used. Existing candidate h is stale; no package was deployed.
