# Current checkpoint — September 30, 2026

The app source is published on `codex/aiedge-ha-app`. This is a development
branch, not a release or live deployment. The earlier dated entries below are
historical checkpoints; this section describes the current state.

- Home Assistant-local storage is the default. No external archive server is needed.
- Number-format UI is connected to the shared physical-reading algorithm, with
  per-dial revolution values, explicit error assumptions, reference highlights,
  leading zeros and derived display precision. No separate reading roles are exposed.
- Relative consumption and average rate are connected to the existing fixed-anchor
  accounting through a generic nested-scale adapter. Saved capture decisions replay
  after an app restart. Clock/interpretation changes start separate relative segments
  and preserve previous records. A rate bound is optional; unresolved turns, jitter,
  contradictions and rejected images cannot become fabricated point values. A
  decreasing estimate inside overlapping uncertainty is withheld, not clamped.
  This output is conditional on unvalidated model-error/rate assumptions and is not
  a lifetime or MQTT consumption sensor.
- Recognition prioritizes the current capture before draining older unprocessed
  images, so a calibration change cannot hide the latest result behind an archive.
- Optional MQTT discovery/publication is implemented with Supervisor service lookup,
  Paho 2.1.0, unique physical-format identity, acknowledged QoS 1 delivery and stale/
  rejected/ambiguous availability handling. Images are not uploaded to the broker.
  There is no cumulative/total_increasing claim or automatic reuse of old entities.
- Overview status updates every five seconds while visible; it preserves editor
  drafts and does not rebuild unchanged thumbnails. Failed connections clear the
  displayed current reading. Current worker failures and historical failures are
  distinct. Local storage health and free space are visible.
- Disk/database failures no longer kill the recognition worker. Invalid reference
  files and extreme/nonfinite landmarks fail validation without replacing calibration.
  Setup is limited to the 16 dials supported by the physical calculation.
- Desktop 1440 × 900 and mobile 320 × 760 / 390 × 844 viewport checks covered light/dark themes, compact
  format layout, reference highlighting, no horizontal overflow, calibration labels,
  and disconnect/reconnect status. Invalid format saves preserve the prior file.

- Invalid saved calibration or number-format files now leave the app accessible.
  A validated replacement preserves the failed original, verifies its hash and checks
  for intervening disk changes. Unreadable storage stays blocked until repaired.
- Crop handles choose the nearest corner and preserve the opposite anchor. Optional
  proportion locking works for drag and numeric edits. Canceling a drag restores the
  original box; selecting a new image cannot discard the draft before it loads.
- Desktop editors keep the image within one pane, with scrolling limited to controls
  on shorter screens. Mobile remains stacked without horizontal overflow. Page routes
  survive reload and browser Back. Refresh retries missing image files. Reference-image
  loads time out after ten seconds; the number-format fields remain usable while the
  preview loads. A stalled-response browser fixture verifies timeout and recovery.
- Browser format saves now complete without a hidden global-function error. Calibration
  saves stay disabled until a change is made. Recovery guidance is shown once.
- Concurrent image-store writers serialize admission, verify duplicate files and leave
  no ledger entry after a failed file write. Damaged inference rows remain preserved
  and unavailable; no older result is substituted. Saved image reads are bounded
  to reject oversized damaged files without allocating their full size. Camera failures distinguish login,
  unsupported API, busy camera, lighting, clock and transport problems.

- Invalid options, unreadable startup storage and damaged MQTT identity leave the
  website accessible with network workers stopped. Originals are not reset.
- Capture history now has durable event IDs and bounded Older/Newer paging. The
  migration preserves original frames, timestamps and model results. Repeated JPEGs
  retain separate capture events while sharing one image file.
- Normal app shutdown drains workers for up to 25 seconds. A 990.8-second loopback
  trial exercised three restarts during capture: 36 events, nine unique archived
  images, no failures or missed slots, and approximately 0.235-second shutdowns.
  The 450 status requests had 0.026863-second p95. Transport times were simulated;
  this does not validate real-camera operation or accuracy.
- Overview offers a diagnostics download without credentials, camera addresses,
  images, meter values or local paths. Recovery and history paging were checked
  in desktop and mobile browser views.
- Eleven pinned Linux wheels have a hash-checked notice inventory, retained in the
  container. Full bundled-native and Debian distribution review remains pending.

- Optional camera clock metadata is stored with each acquisition and checked for
  clock resets, backward ticks and UTC discontinuities. Old records are retained
  without invented clock data. Relative consumption uses compatible metadata;
  firmware emission builds locally, while physical timing validation remains pending.
- History failures stay on Captures and do not hide a successful status response.
  Pending or missing recognition is no longer overwritten by a number-format prompt.
  Alignment and crop rejections point to the relevant calibration check.
- Linux directory entries are flushed before capture/configuration success. Tests
  cover flush failures and uncertain post-rename saves; real power-loss durability
  has not been established on Linux or hardware.
- HTTP connections are limited to 32 and idle reads to ten seconds. Active web
  requests share the 25-second worker shutdown deadline. Stalled connections cannot
  extend that drain indefinitely. Capacity exhaustion returns a bounded busy
  response; the UI distinguishes it from storage failure and recovered in the
  browser fixture. Blocked reference storage leaves the website open
  and stops capture/MQTT without replacing the blocking file.
- Oversized or contradictory stored inference provenance is rejected and preserved;
  it cannot turn an estimate into verified accuracy or a training label.

Camera contract follow-up: the local firmware now emits a per-boot clock ID and
sensor capture tick. The actual capture route was compiled with SDK substitutes
and checked against app persistence: same-boot time, a changed boot, exact replay,
six header-write failures and failed transmission. The test uses a synthetic JPEG
envelope and substituted camera/clock/hash; it does not validate decoding or hardware.
Both authenticated ESP32 targets build: camera-only uses 1,565,736 of 1,945,600
flash bytes, and the full reader uses 1,851,360. Hashed binaries and changed-source
snapshots are retained locally; these are not released managed update packages.
A separate real archived JPEG passed the compiled route's emitted headers through
HTTP transport, storage, native alignment and both actual LiteRT models; its six
estimates survived restart and remain excluded from training and unverified for
accuracy. Evidence: `clock-contract-real-image-20260930.json` and
`camera-clock-candidate-20260930/manifest.json` in the same test directory.

The app also rejects duplicate provenance/framing fields
and noncanonical image lengths before persistence. Evidence:
`server-native-20260929/clock-contract-20260930.json` in the workspace test directory.

HTTP/TLS response headers, images and error bodies now share a 20-second I/O
deadline. Loopback tests cover slow trickle traffic, buffered header/body delivery,
trusted TLS and rejection of an untrusted certificate. DNS still uses the OS
resolver and is not forcibly interrupted. Runtime trust is unchanged; disposable
TLS fixtures are excluded from the container context.

A 470.6-second transport fault trial then exercised the new response deadline and
request-draining server together with recognition. It retained 14 capture events
from 18 requests and nine unique archived JPEGs. Three injected faults (incomplete
clock metadata, duplicate hash metadata and a trickled body) were rejected; one
exact replay added no event. Two app restarts preserved all data. Shutdown took
20.031 seconds while draining the slow response, then 0.219 seconds normally;
no scheduler slots were missed. The 204 status requests had a 0.027494-second p95
and 0.040377-second maximum. Clock reset, UTC jump and missing metadata were all
flagged. Evidence: `server-native-20260929/transport-trial-20260930T0610Z/result.json`
in the workspace test directory. Transport times were simulated, images remain
excluded from training, and accuracy and real-device behavior were not evaluated.

A second 990.8-second loopback trial exercised a simulated camera reboot, a UTC
jump, missing clock metadata and an exact frame replay across three app restarts.
It retained 34 captures from 36 requests (nine unique images), rejected the one
intentionally incomplete clock response and did not add the exact replay as a new
event. There were no unexpected errors or missed scheduler slots. All clock
faults were flagged; 450 status requests had a 0.025564-second p95. This trial used
the capture/recognition workers; the new HTTP request-drain behavior was checked
separately. Evidence: `server-native-20260929/clock-trial-20260929T2135Z/result.json`
in the workspace test directory. Photograph labels and accuracy were not evaluated.

Validation: **163 tests run, 162 passed, one skipped**, plus **21 JavaScript tests**. The skipped check requires the
Linux container. All native/model fixture tests were enabled. Test evidence and source
hashes: `needle-training/firmware-port-tests/server-native-20260929/publication-final-20260930.json`
in the parent Home Assistant workspace. A disposable browser fixture recovered both
saved-file errors and verified preserved original bytes. The real Paho client was exercised against a
loopback MQTT 3.1.1 protocol fixture; this is not a live broker or Supervisor test.

A 245-second local trial processed nine unique archived images with the actual native
pipeline and LiteRT models. Requests were 29.984–30.016 seconds apart; no missed slots
or capture failures occurred. All nine produced dial estimates. Maximum processing
was 0.040718 seconds. The 122 concurrent status requests had 0.023817-second p95 and
0.029649-second maximum latency. Trial capture timestamps/frame IDs were simulated in
an isolated fixture store. All rows remain excluded from training; these results do
not establish accuracy, live ESP32 timing, Wi-Fi behavior or Home Assistant performance.
Evidence: `server-native-20260929/cadence-20260929T061255Z/result.json` in the same
workspace evidence directory.

Still unverified/pending: Linux container execution, actual Supervisor installation,
MQTT discovery with HA, Supervisor backup/restore, compatible remote-camera firmware
on hardware, camera controls/OTA, validated model error bounds, training review UI,
hardware validation of relative consumption/flow and any lifetime-total publication. The current format value is a modulo
register position. Supplied tolerances are assumptions, not measured accuracy.

GitHub rejected the workflow push because the OAuth connection lacks workflow scope.
The prepared `.github/workflows/aiedge-app.yml` has not run. The source-only app branch
omits that unpublished workflow. The published source-only Git archive was checked independently: every Docker COPY
input exists and all 24 manifest asset hashes match. `.gitattributes` preserves
exact asset bytes across Windows/Linux checkouts. Both Docker stages now pin the
Python 3.14.7 slim-trixie OCI index digest; official registry metadata and the
Linux amd64 manifest were verified without claiming a container execution. CMake now defaults to the packaged
header snapshot; CMake execution itself was not tested on this host. The original
AIEdge favicon and a development README are included. No production HA or meter
changes were made.

Consumption validation: 163 app Python checks run with actual native/model fixtures:
162 pass and the Linux-only container check remains skipped. All 21 JavaScript
checks pass. The separate C++ oracle checks 1,000 intervals, 6,000 stationary/jitter
observations, generic scale ratios, 20/200 gas-wheel turns, register wraps, ambiguous
gaps and nondecreasing published consumption points. Twenty-three durable-accounting
checks cover capture timing, unavailable images, restart replay, concurrent workers,
failed/uncertain writes, software/format changes and damaged state. These quantities
are synthetic test cases and do not measure model accuracy.

A frozen-source 451.17-second loopback trial processed 17 capture events from 18
requests, retained two unique images (one actual reference and one synthetic blank
rejection), and drained three stops/restarts. All 17 accounting decisions survived
recovery. No stationary image produced positive consumption, no capture slots were
missed, and no unexpected runtime error occurred. There was one deliberately
incomplete clock response. Status p95 was 0.02582 seconds. Clocks, tolerance and
rate bounds were simulated; the trial does not establish physical accuracy or HA
performance. Evidence: `server-native-20260929/consumption-trial-20260930T0740Z/result.json`
in the private workspace evidence directory. The source snapshot is hash-recorded;
later publication additionally checks the final accounting library built from the
clean source archive.

The final core trial repeated that 451-second exercise with frozen source and the
final accounting library: 17 capture events, all accounting decisions recovered,
zero positive consumption from repeated images, no missed slots and no unexpected
errors. Status p95 was 0.02891 seconds and maximum was 0.04403 seconds. Subsequent
changes affect display precision and layout; the clean publication regression run
covers them separately. Evidence: `consumption-final-trial-20260930T0752Z/result.json`.
An isolated upgrade check preserved the 17 original decisions, inference rows and
both image hashes, started a separate interpretation segment, and replayed the new
anchor identically. Evidence: `final-upgrade-recovery-20260930/result.json`.

Consumption display precision now includes uncertainty at both endpoints. Raw
estimates remain unchanged. On 320-pixel screens the navigation and format editor
fit without horizontal overflow; the save controls stay available while editing.
Dropdown arrows are inset ten pixels. Desktop/mobile screenshots and measurements
are retained in `ui-accounting-20260930/` in the private workspace test directory.

Both native libraries also cross-compile to Linux amd64 ELF shared libraries with
all expected ABI exports. This used Zig on Windows, not the container's g++ runtime.
It is compilation evidence only: Linux execution, container builds and Supervisor
installation remain unverified. Evidence: `linux-cross-compile-20260930/result.json`.

An isolated abrupt-exit test terminated the actual Python process after a capture
commit, during an uncommitted SQLite transaction, and after an accounting commit.
All earlier decisions and image hashes survived; the incomplete transaction rolled
back, and each repeated image recovered without positive consumption. This checks
process-crash recovery on Windows, not physical power loss or Linux durability.
Evidence: `abrupt-exit-recovery-20260930/result.json` in the private test directory.

---

# Server migration status

Local implementation: remote-camera transport, 30-second serial capture scheduler,
actual device timestamps and hashes, immutable image storage, SQLite deduplication,
and durable recognition results keyed by image hash and pipeline fingerprint.
Results never become training labels. Current-image status cannot reuse an older
image's result. Failed inference preserves raw images and records a rejection.

Recognition uses the existing C++ alignment, visibility checks, polar features and
decoder through a native bridge, with the two exact routed int8 models. Enabling it
requires an explicit calibration profile or calibration JSON file, model directory
and ABI-2 native library. Runtime JSON imports support three markers and 1-32 dials.
The visual editor supports explicit marker and dial geometry. A profile must not
be silently used for a different scene or current camera geometry.

Validation, September 28 local time:
- 31 capture/storage/recognition/HTTP/native-profile/setup/asset tests passed with native fixtures enabled.
- Current LiteRT reference kernels matched old TensorFlow reference kernels on
  dense and sparse retained RGB fixtures, including visibility rejection.
- Optimized LiteRT matched sparse output exactly on that fixture. Dense output had
  one score difference, changing one dial position by 0.000080 on its 0-10 scale.
- 26 historical JPEGs replayed: 25 estimated, 1 rejected. Slowest decode + shared
  preprocessing + inference took 0.0493 seconds on the Windows PC. This excludes
  camera/network time and does not establish accuracy or HA-host performance.
- Replay retrieval timestamps were not substituted for unknown capture timestamps;
  historical files were not inserted into the live camera ledger.
Evidence: needle-training/firmware-port-tests/server-native-20260929/.

UI: compact sidebar, one toolbar, inline counts, image/status pane, capture gallery,
System/Light/Dark theme. Mobile 390px checked without horizontal overflow. Live API
recognition output can display dial estimates, but no physical total is fabricated.
The existing localhost preview remains capture-disabled.

Remaining: complete camera/lighting setup and editor interaction testing, generic number formatting/accounting,
MQTT, remote archives, camera-only operation and capture/OTA hardware validation, retention/storage limits,
Linux container/Supervisor validation and release packaging. Docker is unavailable
on this Windows host; its container definition now packages recognition, but has not been built or
executed on Linux and is not a validated release. Production r60 and HA are unchanged.
This is not yet a working meter-reader MVP.

Runtime calibration verification: all 26 historical JPEGs reproduced the frozen path numerically with imported markers and geometry. Dense/sparse tensor equality, reordered two-dial selection, owned profile buffers, closed handles, blank images, invalid crops/pivots/matrices, overlapping markers, duplicate targets and marker hash mismatches checked. Evidence: runtime-reader-parity.json and runtime-calibration-tests.json in the server-native evidence directory. This establishes compatibility, not generalization to other meters.

Setup backend update: explicit four-rim-point geometry and independent image-space
needle pivot now build a runtime calibration. Reference image storage is separate
from the capture ledger. Save preflights the actual reference through recognition,
then atomically persists and switches at a frame boundary. Stale revisions and
failed persistence preserve the active reader. Restart and the calibration-file
CLI path verified with the actual saved reference (setup-activation.json). The six
setup unit tests use a controlled reader double; the separate saved-reference test
uses the real native bridge and models. HTTP setup endpoints and the initial visual editor are now connected; full camera/lighting and accounting setup remain pending.

Visual calibration update: localhost preview now runs the ABI-2 models and exposes
Calibration navigation, a reference-image pane, marker/dial selection, box resizing,
explicit rim/pivot placement, and a single preflight/save action. The real saved
reference was imported through HTTP and saved again through the browser; applied
state verified. Capture remains disabled and its ledger empty. Desktop spacing,
390px overflow and mobile Choose image visibility checked. Corner-drag and complete
new-profile creation still need comprehensive interaction testing. HTTP request
protection, stale revisions, reference retrieval and upload-size limits tested.
The API is localhost-only outside HA Ingress; no public/native authentication claim.
Local process uses .venv-aiedge-server; Docker packaging remains unvalidated on Linux.

Remote capture work: `/api/v1/capture` is implemented locally as an asynchronous
single-camera job with existing light/camera ownership, exact outgoing-JPEG hash,
boot/frame identity and sensor-monotonic-to-UTC timestamp mapping. An NTP sync
must have been observed this boot; invalid/stale frames and clock steps fail.
Vendored cam_hal.c sets the frame timestamp from esp_timer_get_time at frame start.
Physical accuracy of that timestamp has not been measured. Server Basic/Bearer
transport tests exercise real local HTTP, including redirect credential protection.
Production-route host tests cover asynchronous admission, busy rejection, task
creation failures, camera/clock/settings/light/orientation/hash failures, frame
return and light shutdown. SDK, camera and cryptographic hashing are substituted
in that route test; the tests do not prove hardware behavior or crypto correctness.
The timestamp mapping test compiles the production helper and checks drift bounds.

Build command uses the pre-existing P: mapping because ESP-IDF rejects spaces:
`P:/.venv-firmware/Scripts/python.exe -m platformio run -d P:/firmware/AIEdge-publication/code -e esp32cam-managed-open-development`.
This is an open-auth development target, not a deployable authenticated release.
No flash or production/HA configuration changes performed for this work.

Final-source ESP32 development build passed (including the NTP-sync gate):
1,851,048 / 1,945,600 application bytes, 57,472 bytes static RAM. This is the
existing full firmware with a new endpoint, not the smaller camera-only image.
Evidence and source/binary hashes: remote-capture-validation.json in the server-native
validation directory. The dev authentication bypass is explicitly recorded; this
binary has not been flashed, published or promoted as a production release.

Packaging update: the HA build context is self-contained: a manifest-checked native
header snapshot, both exact model files, upstream license/credits, hashed Linux
Python wheel lock, native compile stage, and native/model invocation build check.
Runtime starts with recognition/setup enabled but no frozen calibration selected;
a user must provide scene geometry. Legacy frozen geometry remains compiled only
for explicit replay tests. Windows compilation from packaged headers passed all
31 tests. Linux wheel availability/hash resolution verified; Linux execution,
Supervisor installation, dependency audit and container base digest remain pending.

Storage scope clarification: use the app's persistent /data directory in Home
Assistant for images and capture metadata first. External/network archiving is a
later optional feature, not an MVP prerequisite. The initial archive draft and
configuration hook were removed before testing or deployment. The localhost
preview still stores on this PC; it is not a running HA installation. Capture
workers now start only after the HTTP listener successfully binds, preventing
background captures if service startup fails due to an occupied port.

Camera-only startup preparation: ClassFlowTakeImage now exposes ReadCameraSettings
separately from recognition RGB-buffer allocation. The existing ReadParameter path
still applies settings and allocates under the same recursive camera lock. No
startup mode has been changed or deployed. Inspection found OTA acceptance depends
on three successful on-device reader cycles and a model self-test; remote-camera
mode needs its own explicit capture/transport health evidence before it can replace
that policy. Do not simply bypass those gates or start a camera-only build with the
old acceptance requirements. GPIO initialization currently also occurs in doInit.

Remote-camera target implemented locally: `esp32cam-managed-remote-camera` inherits
the authenticated managed build (not the temporary open-website target). Startup
uses the camera-only parser, requires valid explicit lighting configuration and
GPIO initialization, and does not start the recognition task. Recognition self-test
HTTP jobs are rejected in this mode. The existing full-reader target keeps its OTA
policy. Remote OTA acceptance uses three consecutive timestamp-valid completed
JPEG sends and separate configuration/bundle/fault gates; failed SDK writes or
uncertain readback are terminal for that boot. Policy tests and the actual acceptance
method with SDK substitutes pass. No image accuracy, remote persistence, physical
lighting, rollback recovery or real 30-second cadence is established by these tests.
The initial target build passed at 80.5% application partition versus 95.1% for the
full reader. Final lighting-gate rebuild passed: 1,565,588 application bytes and 54,584 bytes static RAM. Symbol inspection found the remote startup/acceptance functions and no automatic recognition-task function. This is compile/link evidence, not a hardware startup test. No firmware flash.

End-to-end saved-image check: test_capture_pipeline.py passed with the real archived
reference JPEG, HTTP camera simulator, packaged native library and both actual
models. It exercised transport -> hash-checked local store -> six-dial inference,
image deduplication, durable restart readback and a rejected wrong-hash response.
All fixture capture timestamps were simulated and confined to a temporary store;
no historical image was given a fabricated timestamp in the real capture ledger.
No physical total or training label was inferred. This is not hardware or accuracy
validation. The existing full-reader compatibility rebuild also passed (1,851,136 application bytes; 57,528 bytes static RAM).

Home Assistant-local storage follow-through: `/data` remains the default and no
external receiver is required. App configuration now requests `backup: cold` with
no image exclusions so Supervisor can stop writers while copying app data. Actual
Supervisor installation and backup/restore remain unverified. Capture now checks
512 MiB of filesystem headroom plus the maximum incoming image before requesting
a camera frame and rechecks space before storing it. Low/unavailable space prevents
new captures, preserves existing images, and retries on the normal schedule; failure
to persist an error does not terminate the capture worker. The status API exposes
storage health/free bytes and the current worker error. This is not a quota or
retention policy and cannot reserve space against other applications.

Validation: all 38 app tests passed with the packaged native DLL, calibration,
RGB/JPEG fixtures and actual LiteRT models enabled. Six new storage tests cover
low-space admission/recovery, space changes before persistence, duplicate images,
unavailable filesystems, error-ledger write failure and a stopped-app directory
copy/restore. Restore verified file hashes, SQLite integrity, calibration/reference
readback, capture provenance and existing inference without reprocessing. The
restore test uses a fixture reader; the separate full pipeline test uses real
models. Neither substitutes for a real Home Assistant restore. DOCS.md now describes
implemented calibration/recognition and local storage rather than stale placeholders.
No Home Assistant or device deployment was performed in this change.

Physical reading backend added: the ABI 2 bridge now exposes the existing shared
RevolutionReading algorithm rather than a separate Python calculation. Formats
specify every calibrated dial once by index, source units per full revolution and
an explicit position-error assumption. The saved file binds to the full reader
pipeline identity, so model/calibration changes require a new confirmed format.
No default meter scales or validated error bounds are invented. Raw dial positions
remain unchanged and are never promoted to labels. Inconsistent/ambiguous/missing
inputs produce no physical value; overlapping fractional positions are not summed.

GET/POST /api/reading-format exposes the backend format and the current dial names,
directions and pipeline identity. Writes share the setup authorization token,
validate all mappings and optimistic revisions, and atomically save to /data.
/api/status now contains a separate reading result. The number-format UI and
formatted overview display remain pending; this is not a claim they are deployed.
The result is a modulo register position, not monotonic cumulative consumption,
flow, or measured accuracy. Temporal accounting remains pending.

Validation: 50 app tests pass with the rebuilt aiedge_reading.dll and actual model
fixtures. Added tests cover decimal substitution, multi-dial carries, register
wrap, 200:1 revolution ratio, unresolved whole turns, contradictions, changed
pipeline, invalid/missing positions, reordered dial mapping, saved-format restart,
failed-write preservation, revision conflicts, unauthorized API rejection and
physical value in status. Packaged headers and manifest regenerated; Docker smoke
test also exercises the native physical calculation. No live deployment.
