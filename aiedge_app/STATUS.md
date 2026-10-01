# UI candidate - October 1, 2026

The dev10 review candidate adds guided Image, Alignment, Dials, Number format,
Data and Finish steps plus Settings. Compact desktop panes and mobile layouts
keep the image visible while editing controls. An unchanged reference is retained,
navigation cannot be overwritten by a stale save, and selecting the sixth dial
survives route updates.

Setup photos are explicit asynchronous jobs, separate from scheduled-capture
observations, inference and training. Navigation reads only local app data and
cached camera configuration. Camera LED/exposure/orientation controls remain on
the camera website because the capture protocol has no settings-management
contract; full camera-management parity is not complete. See UI-PARITY.md.

Local validation: 282 host checks passed with one Linux-only check skipped; all
56 UI checks passed. Host replay includes protected archived images and is not an
accuracy claim. Models, native cores and physical calculations are unchanged by
this UI candidate. The prior dev9 Linux package check succeeded; this candidate
needs its own Linux package check.

This is a review candidate, not a live Home Assistant update. The installed app
remains at the dev8 checkpoint below. No camera firmware, lighting settings,
capture/MQTT options or live data were changed.

# Previous installed checkpoint - September 30, 2026

September 30 dev8 checkpoint: experimental `0.2.0-dev8` is installed and
started in Home Assistant after explicit chat approval, a fresh verified Time
Machine backup and an AIEdge-only cold backup. Smart Backup was restored and
verified. Automatic updates for experimental AIEdge are now disabled.

The approved short trial stored three unique real-camera JPEGs with zero capture
failures. Actual capture intervals were 29.99 and 29.95 seconds. Capture-to-receipt
times ranged from 1.61 to 1.94 seconds; decoding, alignment, preprocessing and
inference took 12 to 21 milliseconds. Both app stops reached the stopped state;
structured logs show drained requests and no pending workers. These stops occurred
after image transfer, so draining a hardware transfer in flight remains unverified.

Original app options, reference, six-dial calibration, number format, pipeline
identity and saved image history were verified after restoration. Capture and
MQTT are off. No camera firmware, lighting, image-quality setting or device restart
was changed by this deployment. New images are protected from training.

This establishes a short capture/shutdown trial, not sustained reliability or
reading accuracy. Fine absolute position and skipped whole wheel turns remain
unresolved under the current history and rate assumptions. The user's `02558`
confirmation belongs only to its specific earlier image. It is never a fixed
prefix for subsequent captures. User-operated high-flow calibration is planned;
it was not part of this trial. Evidence and rollback: `app-shutdown-dev8/` under
`needle-training/firmware-port-tests/server-native-20260929/`; cold backup `030a429c`.

Older checkpoints below are historical.

September 30 dev7 checkpoint: experimental `0.2.0-dev7` is installed and
running in Home Assistant. Fresh verified Time Machine and AIEdge-only backups
preceded the update. Reference, six-dial calibration, ft3 format, original
options and recognition pipeline were preserved. The approved temporary capture
trial stored one new 640 by 480 JPEG through the actual Linux app client; local
readback verified its 29,327 bytes and SHA256. Capture-to-receipt time was 5.05
seconds; this is not the full request duration. All six dial estimates were
produced in about 19 milliseconds including decoding/preprocessing/inference.

The trial ended early: the coordinator treated a startup ingress HTTP failure
as terminal, then did not wait for its stop request to finish. Supervisor later
reported an error state with no active app jobs. Original options were restored,
AIEdge restarted successfully, and saved data/image persistence was verified.
Capture and MQTT are off. The receipt is consumed as partially verified; no
trial or uncertain stop was blindly retried. The coordinator's startup waiting
and stop observation are corrected locally with 11 passing fake-Supervisor
checks. Sustained capture cadence and clean active-capture shutdown still need
verification. No ESP32 firmware, lighting, quality setting or restart changed.

The current combined physical reading remains ambiguous. With a 0.1 position
error on the 1,000-ft3 dial, several full 5-ft3 secondary turns fit a single
image. The diagnostic first-five-dial value is only an unverified estimate;
no live format or tolerance was changed to manufacture a precise total.
Real-image accuracy remains unverified. The new trial image is excluded from
training. Evidence, backup identifiers and restore instructions are in
`needle-training/firmware-port-tests/server-native-20260929/app-transport-dev7/`.

Previous dev6 checkpoint follows.

September 30 app update: experimental `0.2.0-dev6` is installed and started
on Home Assistant. Fresh Time Machine and AIEdge-only backups were verified;
the reference image, six-dial calibration, ft3 number format, options and native
pipeline identity are unchanged. Automatic capture and MQTT remain off. No
ESP32 firmware update or device restart was made during this app deployment.

All three approved local Windows requests through the exact frozen dev6 client
were issued once and timed out at the absolute 20-second deadline. Traced
responses had valid JPEG and timestamp headers but incomplete image bodies.
Passive downloads of the already saved reference JPEG also stalled with both
clients. The meter still reported camera ready and 42m 46s uptime after the
capture attempts. A later RSSI read was -84 dBm. A bounded full-size ping probe lost two of
four packets; four subsequent small pings passed. These sequential small samples
support a network contribution, not an established sole cause or sustained loss
rate. Reliable transfer,
real-image accuracy, clock continuity and sustained cadence remain unverified.
The app update approval is consumed as partially verified: installation and
preservation passed, capture validation failed. Evidence and restore steps:
`needle-training/firmware-port-tests/server-native-20260929/app-transport-dev6/`.
The client change removes the separate five-second idle cap while preserving
the total deadline; its local delayed-body regression passes, but the current
hardware transfer still stalls.

Previous firmware checkpoint (before the dev6 app update):

Latest camera state: the approved timestamp correction is installed and its
exact bundle boot identity is verified. After the user cold boot, the camera
became ready; settings/reference hashes and embedded pages passed verification.
All three approved captures were requested exactly once. One diagnostic-client
capture returned a valid 640 by 480 JPEG with matching hash, UTC, numeric tick
and frame ID; transfer took 14 seconds. Both normal app-client requests timed
out. Final camera status remained ready and uptime continued without another
restart. This verifies the timestamp correction on one image, not reliable app
capture, clock continuity, accuracy or sustained cadence. HA capture/MQTT remain
off. At this earlier firmware checkpoint, a local client timeout correction passed
39 host capture/clock checks, including a delayed-body regression. Its subsequent
dev6 app deployment and failed hardware transfer checks are recorded above. The
GPIO32 warm-start reset defect is also local and unproven as the hardware cause.
Automatic bootloader rollback remains absent. Evidence: timestamp deployment
`result.json`; the single-attempt approval is consumed as partially verified.

The camera checkpoints below are earlier evidence.

Latest camera checkpoint, September 30: the approved recovery package now boots
on the original meter, with camera ready, embedded recovery pages accessible and
saved configuration/reference bytes preserved. All three approved captures were
requested. The firmware emitted invalid monotonic ticks (`ld`) and repeated frame
suffixes (`lx`), so none was admitted as a valid capture. Two diagnostic JPEGs
were preserved with valid raw hashes and UTC timestamps, excluded from training.
The 64-bit formatting correction passed local host regressions; deployment of that
correction remains separate. HA app capture/MQTT are still off. The old migration
and SD recovery entries below describe earlier checkpoints, not current readiness.

The app source is published on `codex/aiedge-ha-app`. Experimental version
`0.2.0-dev6` is installed on one Home Assistant host; this is not a release.
The earlier dated entries below are
historical checkpoints; this section describes the current state.

- The approved camera migration selected its new flash image, then panic-reset
  repeatedly on the production meter at 10.1.0.127. The approved SD lighting
  workaround was tested on that meter and failed before its intended validation
  message. The user then moved the same SD card into a different backup board,
  connected on COM10 at 10.1.0.83. Its September 25 firmware remains in that
  board's flash; retained SD logs provide the failed meter's startup evidence.
  They do not contain its UART backtrace. No validation captures were taken.
- A separate-stack startup correction and persistent internal-NVS interrupted
  startup guard are built, packaged and tested locally. Host tests cover the
  production startup admission branch, storage failures and both status modes;
  they do not prove the hardware crash cause or recovery. The guard does not
  write to SD and commits internal NVS twice per successful initialization,
  never per capture/status request. Existing device logging still writes to SD.
  The separately approved SD recovery disabled only the failed application's
  bundle index and restored the original configuration. The original meter
  at 10.1.0.127 now serves reduced HTTP status, detects its camera and reached
  3m 51s uptime in bounded checks. Capture settings remain unavailable. The
  updater status API responds, but its bundle-dependent page returns 404.
  Known-working firmware restoration and pre-HTTP recovery remain unverified.
  Neither board has received the corrected firmware. The HA app is unchanged.
- Firmware-resident recovery status and update pages are now implemented and
  built locally. They do not depend on SD web assets; the status page avoids the
  old broken links and repeated per-visit SD error write. The existing update
  client preserves separate upload/verify/install actions and no automatic
  restart or uncertain-write retry. Handler/auth/failure tests and seven client
  regressions pass. Desktop/light and mobile/dark previews were inspected; the
  390-pixel mobile layout has no horizontal overflow. Exact package identity and
  host staging evidence are in `server-native-20260929/recovery-pages-validation-20260930.json`.
  This does not establish production firmware recovery or authorize a new flash.
- The exact recovery-flash review now binds the current original-meter baseline,
  candidate ZIP/binary and all 141 packaged assets. A separate deployment runner
  passed 27 local regressions covering explicit approval/exception gates, fresh
  Time Machine backup and Smart Backup restoration, retained file hashes,
  uncertain writes without repeats, same-job observation, one restart, camera
  admission and three simulated hash-checked JPEGs kept excluded from training.
  A real missing-approval command also refuses to start under Python optimization.
  These tests use simulated endpoints and temporary stores, not hardware.
  Evidence and operator instructions: `server-native-20260929/flash-readiness-20260930/`.
  Exact OTA approval remains pending; no new device or HA write was made.
- The latest local validation passed 213 app tests with native libraries,
  both pinned models and private archive replay, plus 23 dashboard/crop/reference
  UI checks. The Linux-only packaged-runtime test was skipped on Windows. A new
  production startup-helper test passed 15 cases, including the original card
  configuration and rejection of the temporary recovery configuration. Sensor
  setters and journal I/O are substituted; no physical boot/capture is claimed.
  September 30 PyPI metadata still matches all four direct dependency pins.
- Locally prepared app changes add one passive readiness request per scheduled
  capture cycle. Unready settings, an unsynchronized clock, a busy camera,
  unavailable camera or demo mode prevent the picture request. The snapshot is
  distinct from capture completion, image persistence and reading accuracy.
  This requires the new camera status API and is not deployed on Home Assistant.
- The approved dev3-to-dev5 update passed on September 30 at 18:11 UTC. A fresh
  Time Machine backup and cold app-only Supervisor backup were verified before
  deployment. The actual Linux runtime accepted the saved six-dial reference;
  its image hash and calibration were preserved. The existing ftÂ³ number format
  was rebound to the new pipeline and persisted after an app-only restart.
  Capture and MQTT remain disabled. This verifies installation and persistence,
  not real-image accuracy or a live camera workflow.
- The `0.2.0-dev3` container built and started on a Home Assistant Linux amd64
  host on September 30. Read-only checks verified the HTML/CSS and status, setup,
  number-format, diagnostics and history endpoints. Storage is ready, with zero
  captures and capture/MQTT disabled. Python 3.14.7 and the pinned dependency
  versions are reported. The approved saved-image test passed: three markers, six dial crops and separate
  fixed pivots were accepted by the actual native/model runtime. The reference hash,
  calibration and ftÂ³ format persisted after an AIEdge-only restart. Capture and MQTT
  stayed disabled. Time Machine and a cold app-only Supervisor backup were verified
  before the writes. The full Linux suite and live camera/MQTT tests remain pending;
  this is not an accuracy or release claim.
- The development repository has root metadata and a branch-specific installation
  guide. Use `https://github.com/isentropik/AIEdge#codex/aiedge-ha-app` in HA;
  the GitHub `/tree/` page URL cannot be cloned as a repository.
- Phone/tablet controls have larger touch targets and 16px input text. Crop handles
  remain visible at smaller image scales, with a wider touch hit area. All four
  pages were checked at 320, 390, 768 and 1280px without horizontal overflow;
  actual phone Safari/Android and HA Ingress rendering still need a device check.
- Installed `0.2.0-dev5` compares exact source pixels per dial after
  validating alignment. Identical regions reuse extraction and model results; changed
  regions take the full path. Changed registration, failed alignment, poor visibility,
  sampling changes and model errors cannot reuse an unvalidated result. Cached work
  remains an estimate, with fresh capture timestamps and normal physical accounting.
  All outputs matched full processing across nine archived images. That photo set
  produced no reuse hits: sensor/image variation makes the exact gate conservative.
  Identical-frame tests show a reduction, but whole-image deduplication already
  handles repeated identical JPEGs. No live-camera speedup or accuracy gain is claimed.
- Calibration can suggest separated textured marker patches outside configured dial
  crops, with an undo action. Proposals stay in the draft and require review; they do
  not recognize printed symbols or guarantee that a feature is stationary. Insufficient
  texture or spacing leaves the existing markers untouched.
- Saved-image review is available from Captures, with manual 0â€“10 positions, unknown
  entries and a separate numbered calibration-reference map. Immutable revisions
  preserve the image hash, calibration, model hashes and pipeline identity. Duplicate
  images share a review; stale calibration/tab edits are rejected. Review does not
  update training permissions or claim accuracy.
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
- Desktop 1440 Ã— 900 and mobile 320 Ã— 760 / 390 Ã— 844 viewport checks covered light/dark themes, compact
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

Validation: **207 tests run, 206 passed, one skipped**, plus **30 JavaScript tests**. The skipped check requires the
Linux container. All native/model fixture tests were enabled. Test evidence and source
hashes: `needle-training/firmware-port-tests/server-native-20260929/publication-changed-dials-20260930.json`
in the parent Home Assistant workspace. A disposable browser fixture recovered both
saved-file errors and verified preserved original bytes. The real Paho client was exercised against a
loopback MQTT 3.1.1 protocol fixture; this is not a live broker or Supervisor test.

A 601-second mixed capture/review trial processed 21 copies of one archived image,
including 76 deliberately synthetic review edits, one app restart and one injected
camera HTTP 503. It retained the expected camera failure, with no unexpected test
errors. The 1,184 web requests had 0.032-second p95 and 0.08182-second maximum
latency. Earlier accounting records, image hashes, inference results and training
exclusions were preserved. Review entries in this disposable fixture are not real
labels. Duplicate captures are not new accuracy evidence. Evidence:
`server-native-20260929/review-capture-trial-20260930/result.json` in the workspace.

A 245-second local trial processed nine unique archived images with the actual native
pipeline and LiteRT models. Requests were 29.984â€“30.016 seconds apart; no missed slots
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

Consumption validation: 173 app Python checks run with actual native/model fixtures:
172 pass and the Linux-only container check remains skipped. All 21 JavaScript
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

A final 60-second local browsing trial used eight concurrent clients across status,
capture history, original JPEGs and diagnostics. All 1,813 requests succeeded;
p95 was 0.03322 seconds and maximum was 0.13745 seconds. Image hashes and all 21
accounting decisions were unchanged. This used an isolated saved-photo store on
Windows, with no camera or Home Assistant access. It is not an HA-host benchmark.
Evidence: `browsing-load-20260930/result.json` in the private test directory.

The portable validation runner explicitly requires both native libraries, both
models, durable accounting, number formatting and generated-image coverage. It
rejects missing test files and unexpected skips. Three generated-image checks use
both actual models, reject absent markers and replay saved stationary decisions;
they do not verify real-image accuracy. Seven runner checks guard missing and
skipped required coverage. Optional private archived-image replay must be supplied
as a complete fixture set or explicitly omitted, with every skipped test listed.
The prepared Linux workflow was corrected to run accounting and require packaged
startup through this runner. It remains unpublished and has not run on Linux.

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
