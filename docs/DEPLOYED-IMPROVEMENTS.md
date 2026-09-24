# AIEdge deployed improvements

[Open improvement backlog](IMPROVEMENTS.md)

This archive records released changes and their actual evidence. It does not imply every feature has passed long-term testing. Local-only edits stay in the open backlog.

## Test-board archive rejection counters — September 23, 2026

The archive page now shows captures refused at handoff and queued captures that could not be saved. It explains that recognition continues and that rejected captures are not guaranteed archived. Authenticated OTA and reboot passed; configuration and password were preserved. Readback matched both packaged web assets, and a DOM fixture rendered the returned live counts correctly. Archiving stayed disabled. This does not establish browser layout or physical outage handling. [Failure behavior and evidence](IMAGE-ARCHIVE-FAILURES.md).

## Test-board cumulative turn tracking — September 23, 2026

Installed source `7cf92c8` through authenticated compressed OTA. Uniquely established wheel turns are retained between observations without summing positive jitter. Portable cumulative, checkpoint, session and history checks and the ESP32 build pass. Startup verified the expected bundle, unchanged configuration and retained password. Six frozen inference vectors matched all output bytes; running this diagnostic left accounting unchanged. Nine representative web routes denied unauthenticated requests.

Physical-sequence accounting, real-image accuracy and sustained cadence remain open. The firmware uses default uncertainty with no assumed maximum-flow bound; the synthetic test's bound is not silently applied to the meter. [Validation details](METER-ACCOUNTING-VALIDATION.md).

## Test-board alignment preview encoding — September 23, 2026

Removed a raw-preview JPEG encode that was overwritten by the annotated preview during the same stage. Preview length is initialized and cleared before processing. The actual-method host test covers both alignment modes and temporary-image allocation failure. After deployment, one before/after hardware pair measured the stage at 3.887154 and 3.498432 seconds; both previews decoded at 640 by 480. Both trials restored configuration exactly. Recognition rejected both scenes, so this is not accepted-reading accuracy or full-cycle performance evidence. See [measurement scope and evidence](PERFORMANCE-MEASUREMENTS.md).

## Test-board authentication and USB recovery — September 23, 2026

The private test application now requires website authentication. USB password setup and password-only recovery passed; configuration bytes and the Wi-Fi connection were preserved. An authenticated OTA using an uncompressed ZIP completed installation and restart with the password retained. The corrected application also accepted a console command immediately after binary installer traffic, without the previous extra-newline workaround. The loader version of that boundary fix remains unverified on hardware. These results do not establish encrypted transport, power-loss recovery or a public release.

## Test-board compressed OTA staging memory fix — September 23, 2026

USB recording identified SDMMC `ESP_ERR_NO_MEM` while reading a compressed ZIP. The read returned 543 of 1,672 requested bytes; SD log writes failed at the same time, concealing the detailed failure from the web log. ZIP inflater, dictionary and index allocations now request PSRAM explicitly so they do not consume the internal memory needed by SDMMC.

The fix was installed through authenticated OTA using an uncompressed package. Restart verification confirmed the expected running bundle, unchanged configuration and retained website password. A new compressed staging-only trial then verified all runtime files successfully; USB recording contained no staging or SD read/write failures. The probe was not installed. Allocator host checks cover PSRAM-only requests, multiplication overflow and failed-reallocation preservation; device staging regression checks and the ESP32 build also passed.

The subsequent preview-encoding candidate also completed a full authenticated OTA from a compressed package: staging, application write, reboot and running-bundle verification passed. Configuration bytes and the website password remained unchanged. This adds one complete compressed installation, not sustained-load or power-loss validation.

Private evidence: `aiedge-zip-memory-candidate/ota/result.json`, `aiedge-compressed-memory-probe/ota/result.json` and `aiedge-preview-encode-candidate/ota/result.json` under the workspace firmware-port-tests directory. These private test packages are not public releases. Broader update/recovery coverage remains in the open backlog.

## 0.1.10 development release — September 22, 2026

Published through GitHub Releases and the web installer. The matched test-board installation completed; camera capture was not tested because the camera was disconnected.

- **Installation task stack:** moved large transfer/extraction allocations off the task stack. Recorded installation passed ZIP extraction and firmware writing without the earlier stack overflow.
- **Application SHA startup failure:** software SHA-256 retained full file verification and allowed application startup on the test board. The underlying hardware-SHA failure mechanism is not established.
- **Application web routes:** increased handler capacity so the homepage could register; verified successful HTTP responses after installation.
- **System-information JSON:** escaped values through cJSON; the endpoint returned valid JSON.
- **Homepage query strings:** root URLs with the installer timestamp now resolve to the homepage.
- **Automatic loader-to-application transition:** checked application identity and homepage readiness, then navigated automatically. Browser transition was observed without clicking Refresh.
- **Download wording:** loader action says “Download to device and install.”

Evidence: source build commit `5ea564689bc39126aa39655efd00108edd13ba79`; public installer commit `2e936991de35f2839380f458711eb630ce2a36e2`; recorded hardware run `recorded-20260923T063329Z`. Public image SHA-256: `73014430b3522df2efa2ae9b0f02e240a3e488f707595520d0db0401b05464c8`.

A later recurrence involved a board identifying as 0.1.8 and a stale installer tab also showing 0.1.8. Preventing stale-tab reuse remains open. Subsequent test-board deployments are recorded below; they are not yet public releases.

## Test board only: 0.1.11-test loader — September 23, 2026

Not a public release. Loader flashed and verified at 115,200 baud with a fresh full-flash recovery copy; no SD formatting or NVS overwrite. Saved Wi-Fi reconnected automatically. The sufficient-space preflight passed and reported actual FAT free space.

The local package connection failed before any download bytes, and the loader remained responsive with Retry available. This does not verify application installation, a full-card rejection, or the application camera/storage-recovery behavior. Those checks remain in the open backlog.

## Test board application verification — September 23, 2026

The retry with loader 0.1.11-test2 downloaded and verified candidate `7f5b07ad7a80e3e96391948007d7c6595220a675007d3908f15d87933e31368b`, installed its SD assets, wrote the inactive firmware slot and booted the application. Recorded run: `recorded-20260923T073703Z`. Earlier failed attempts above remain historical evidence.

- Normal AIEdge homepage loads with the camera disconnected; readings show unavailable and settings/maintenance remain accessible. Browser rendering and HTTP routes verified.
- Capture, illuminated capture, streaming and recognition-start endpoints return explicit camera-unavailable responses without crashing the application.
- Six frozen inference vectors completed on the ESP32: all 360 output bytes per vector exactly matched the desktop reference. Inference took 260,820–266,296 microseconds per vector. This is runtime parity for one source frame, not camera accuracy or full-cycle timing.
- Temporary package-download firewall exception removed and verified absent. Wi-Fi and SD contents preserved; production meter untouched.

Private evidence: candidate `hardware/http-verification.json`, `runtime-result.json`, recorded USB/events. Firmware-resident missing-SD recovery is included but physical no-card behavior remains untested. Public installer remains 0.1.10. Installed version text still inherits upstream metadata, and cosmetic punctuation repairs await the next package.


## Test-board UI deployment — September 23, 2026

The analog-only build and revised setup, settings, recognition, history and system pages are installed on the test board. Fifteen served assets matched the package byte-for-byte. Camera detection is working. A journaled configuration save and readback, stale-edit rejection (HTTP 409), and restoration of the original config all passed on hardware. Setup/save callers now stop when persistence fails.

A deliberately interrupted package transfer at 589,100 bytes was rejected; the loader remained responsive. Restarting and retrying the complete package successfully installed and booted the application. This is download-interruption recovery, not proof of power-loss recovery during flash writing. The full page interaction audit, in-app Wi-Fi editing, and accurate build/version display remain open. A local browser setup-confirmation check stalled in browser automation and is not counted as passed. Public installer/release artifacts have not been updated to this test candidate.

## Full-frame diagnostic and build identity — September 23, 2026

Test board only, candidate application SHA-256 `191b738f6a1e2a60f7bce6fbe99cc42855eedbb89a24975c82ae68d25114a1ce`, recorded installation `recorded-20260923T085333Z`. Camera detected; application and web metadata now report the matching AIEdge build/version.

The full RGB-frame diagnostic passed marker registration and all six dial preprocessing/input and inference/output byte comparisons against the frozen reference. Processing measured 27.020280 seconds, including 3.550585 seconds for registration; the separate six-vector control also matched exactly. The largest observed status-request duration during this one run was 234 ms. These are one-frame implementation-parity results, not live camera/JPEG-to-publication timing or independent reading accuracy.

The first locked candidate failed cleanly because its requested 921,600-byte RGB heap block exceeded the largest available block of 901,120 bytes. The corrected candidate puts RGB in the unused verified-model workspace and separately allocates the smaller preprocessing scratch buffer. Both diagnostic paths hold camera and processing access to protect shared memory. Failure evidence is retained.

The private fixture/package was transferred only to the test board; temporary server and firewall access were removed and verified. No private images were published. Public installer/release artifacts remain unchanged. Physical power-loss recovery and the complete UI interaction audit remain open.

## Test board: accurate cycle outcome reporting — September 23, 2026

The flow wrapper now preserves the controller result; the scheduler distinguishes completed, failed, and skipped/busy rounds. Actual-source host checks passed all three reporting paths and running-flag cleanup; 12 controller failure regressions and the ESP32 build also passed.

The candidate was installed using loader 0.1.11-test7 after verifying the test board MAC on COM8. Its normal camera cycle rejected missing/mismatched meter markers and logged `Round #1 failed (12 seconds)` at warning level, matching the failure telemetry. Original configuration was restored byte-for-byte and the camera remained available. This verifies failure reporting, not successful recognition accuracy. Wi-Fi and SD contents were preserved; no formatting.

Evidence: `recorded-20260923T171859Z`, `normal-pipeline-outcome-retest-20260923`. Application SHA-256: `cbd4bd4dbe3f93ce292d44a876e46394e780c64e444253745252519b72d5ea65`. The private test package and public installer remain separate; no public binary release is implied.

## Test board: archive SD writer — September 23, 2026

The direct-descriptor archive writer was installed using loader 0.1.11-test8 and verified with one actual capture: one image saved on SD, zero enqueue rejections. Partial-write/sync/close fault tests also pass on the host. This closes the `fdopen`/FAT VFS write failure only. HTTPS delivery remains open because the application's HTTP-client HTTPS support was disabled. The queued image is preserved, original settings restored, and temporary receiver/firewall removed. See [hardware evidence](ARCHIVE-HARDWARE-TRIAL.md).


## Test board: verified HTTPS archive delivery and installer memory fix — September 23, 2026

Installed with loader 0.1.11-test11; application SHA-256 `67d7fd877bed293cbe0ff792c81d9c36f4e3f0850028f797080fa20a82296166`. HTTPS is enabled and guarded at build time. A bounded transmit buffer fits the capture metadata header. The bundle verifier releases redundant manifest/ZIP allocations before final readback, avoiding the observed SD DMA allocation failure while preserving all verification checks.

One original queued camera JPEG was delivered with matching hashes and original capture provenance after application updates/restarts. The board acknowledged delivery and cleared its queue, with zero new captures or upload/cleanup failures in the final retry. Original configuration and disabled archive state were restored; temporary receiver, credentials and firewall access removed. Actual-source host verification/transaction and transport tests passed. See [full evidence and limits](ARCHIVE-HARDWARE-TRIAL.md).

This closes the observed SD writer, disabled-HTTPS, metadata-buffer and verification-memory defects on the test board. Sustained operation, wider server compatibility, concurrent recognition and physical interruption tests remain open. No private fixture was published, and the public installer binary remains unchanged.


## Test board: destination-bound archive recovery — September 23, 2026

Installed with loader 0.1.11-test12; application SHA-256 `9e9b0dcdca090f9debc490b9a8fd55154ea0ca7112eac218fb6df0c04804359e`. Changed credentials left the original queue untouched and sent no images. Restoring the original credentials recovered and cleared the queue after acknowledgment, using the same previously approved image with zero new captures. The receiver retained exactly one unchanged record. Original settings were restored, archiving disabled, and temporary receiver/firewall access removed.

The earlier inconclusive test remains documented. This pass verifies credential-change isolation and restart recovery, not every possible destination change or sustained performance. Host tests cover the other namespace inputs. See [hardware evidence](ARCHIVE-HARDWARE-TRIAL.md). Archive setup and retained-queue management remain on the open list. The public installer binary is unchanged.


## Test board: archive settings interface and recovery — September 23, 2026

Installed using loader 0.1.11-test13; application SHA-256 `0b03dc0d42c62a4500e0eedb7c178eb063ae81abaee5dba43eaf8ff4e51345b5`. Settings now links to the optional image archive page, with server address, port, device name, token/certificate retention, theme support and live queue status. Saves use one validated revision, reject stale browser edits, preserve active upload destinations and explicitly require restart. Interrupted first-save/replacement recovery is connected to startup.

Actual-board tests passed saving, stale-edit rejection, restart persistence and recovery from deliberately incomplete files. Original settings were restored, archiving remained off and all cycle counters stayed zero. Exact UI assets were verified on the board; mobile light/dark rendering passed locally. See [evidence and limits](ARCHIVE-HARDWARE-TRIAL.md). This does not constitute physical power-loss coverage or a public binary release.

## Installer release freshness - September 23, 2026

Published site commit `998c333` adds a verified version label and release checks
on returning to the page, periodic visible-page checks, and expired connection
clicks. A changed version disables new connections and requests a refresh.
Existing dialogs and verified firmware blobs are preserved. An unavailable check
blocks an expired new connection until checking succeeds. Already-open
installations are not cancelled or retroactively version-checked.

Watcher and page-controller tests passed for fresh, expired, offline, superseded
and concurrent requests. The vendor dialog is appended separately to the document
body. All three live Pages files matched their committed Git blobs after
publication. This verifies served code and simulated controller behavior, not a
new physical USB flash. Firmware binaries and loader version were unchanged.

## Interrupted staging recovery - September 23, 2026

Source `bb6aade` is installed on the test board in bundle
`ec1a54e3883dddd0e86ed8d2641e32de57ff946ee2229a33f33899b55d04f5cb`.
A software restart during an active staging job originally left the next attempt
at `busy_or_staging_conflict`. The running firmware and settings survived.

The repair preserves the interrupted directory under
`/sdcard/bundles/interrupted/<bundle-id>-<slot>` before extracting a fresh copy.
It never removes prior evidence or modifies completed bundle objects. There are
32 retained slots per bundle; exhaustion or a preservation failure stops staging.
Retained files consume SD space and are not automatically deleted.

Actual-source host tests passed preservation, conflicting files, a blocked
recovery directory, and the retention limit. The complete miniz stager passed
13 cases including retry after a failed sync, with retained bytes unchanged.
Verification, boot-selection, index and transaction regressions also passed.
The ESP32 build and authenticated OTA/reboot verification passed.

On hardware, retrying the original interrupted probe now returned `staged`.
The retained original manifest matched its source bytes. Configuration and
password remained intact; the probe was never flashed or selected for boot.
This is software-restart staging recovery, not sudden-power-loss durability or
recovery from interruption during firmware flashing. Those tests remain open.
Private evidence: `aiedge-stage-interruption-probe/recovered-hardware.json` and
`aiedge-stage-recovery-verified-candidate/ota/result.json` under firmware-port-tests.


## Interrupted installation-index retry (September 23, 2026)

Source `3bf0813` is installed on the test board in bundle
`90818ec0a5b95252725e752c3393ce26194110f193857bb48494af76805b4236`.
An interrupted index write previously left a `.pending` file that blocked retry.
After verifying the candidate bundle, the repair preserves this file as
`.pending.interrupted-N` and writes a fresh index. Existing final mappings remain
immutable. Preservation is bounded to 32 slots; exhaustion or a conflicting
non-file stops installation. Retained files are not automatically removed.

The actual-source host suite passed 14 index cases, including failed sync,
truncated/conflicting/oversized pending content, retention exhaustion, and a
pending directory. All 82 bundle, boot-selection, index, transaction and staging
cases passed. The ESP32 build and normal authenticated OTA/reboot passed;
configuration bytes and website password were preserved.

This proves normal deployment and host recovery behavior. It does not establish
hardware interruption recovery during index publication, flash writing, or
physical SD power-loss durability. Those checks remain open.
Private evidence: `aiedge-index-recovery-candidate/ota/result.json` under
`needle-training/firmware-port-tests`; public regression suite:
[`tools/bundle-tests/test_bundle_recovery.py`](../tools/bundle-tests/test_bundle_recovery.py).
See [run instructions](../tools/bundle-tests/README.md) for dependencies and limits.

## Test-board capture and rotation memory access

The camera uses a contiguous RGB copy, and rotation/translation traverse rows.
Full-frame byte tests and transform parity tests passed. Both are installed,
with original settings restored after bounded hardware timing trials.
Individual measurements reduced the capture stage from 6.88 to 4.67 seconds
and the alignment stage from 3.92 to 1.87 seconds; these are not sustained
valid-reading cadence measurements. See [camera evidence](CAMERA-COPY-VALIDATION.md)
and [rotation evidence](ROTATION-TRAVERSAL-VALIDATION.md).

## Test-board archive upload deadline

Settings and image requests share one network timeout budget. Failure/retry
regressions passed and managed OTA preserved configuration and authentication.
A physical slow-server test remains open. See [validation](ARCHIVE-UPLOAD-DEADLINE.md).

## September 24 - saved-reading load rollback (test board)

Bundle `bbff5440551f17555c8bdffba21d8a5454f5722bcc8da49285dce522342290cc` preserves prior runtime reading fields if loading fails after a valid row. Actual-method host fault coverage and the ESP32 build pass; managed OTA, verified boot, preserved config/profile/password and exact six-dial saved-image parity pass. UI/runtime assets remain unchanged. This does not make legacy saved-file writes atomic or validate physical power-loss durability. See [development status](STATUS.md) for evidence.

## September 24 - strict saved timestamps (test board)

Bundle `f4681eda427aa4e2a035bd6fa825a6413eec0df1a25423dab43a650d9bdee01e` rejects impossible dates, honors saved numeric UTC offsets and excludes future readings from freshness. Actual-loader host tests, ESP32 build and verified OTA/boot pass; config/profile/password and all runtime assets are preserved. See [development status](STATUS.md) for limitations and evidence.


## Publication-checkout build and alignment guidance — September 24, 2026

The test board now runs bundle `ee3deff18d1a94f8d544cc668acbf736677a2d4fb5156adbc7314833a0107383`, built directly from the AIEdge publication checkout. The local package workflow now targets that checkout for firmware and tests, and includes an explicit current-UI validation gate. For this candidate, 78 host scripts and a clean build passed; six supplemental current-UI checks passed, with all 245 inventoried package hashes verified.

Authenticated managed OTA, reboot and bundle verification passed. Original configuration, meter profile/revision and password protection were preserved. The changed alignment page and two build metadata files matched the package when served. Alignment guidance explains fixed distinctive marks, spacing, and the editor's current two-marker limit.

One frozen six-dial sparse saved-image diagnostic completed in 14.293106 seconds with exact tensor/output parity, zero camera cycles and unchanged configuration. This is a port/runtime check, not new accuracy evidence or complete capture cadence. An initial read-only preflight timed out before any mutation; a later USB observation showed startup, and the unchanged previous bundle was verified before installation began. The outage cause remains unproven. Production and the public installer were unchanged.


## Saved-history units and camera-independent profile startup — September 24, 2026

Test bundle `9d0fdc7a4d249ed72f97f944dbd1e05cf8b93d1acabaeaae537e80b399750f37` restores compatible saved display preferences before HTTP startup even if camera initialization fails. Storage/bundle failures keep the preference inactive; journal recovery is shared with flow reload. Saved-history diagnostics now offer ft3/m3 display conversion without rewriting canonical stored totals, and retain unknown bounds and gap warnings.

79 host scripts, six UI checks and a clean ESP32 build passed. Managed OTA and verified boot preserved configuration/profile/password. Hardware reported camera unavailable while profile activation was `display_only` before any settings write. The history preference switched ft3 to m3 and back without restarting; canonical fields and original preference were preserved. The board had empty history, so this hardware check proves activation and null handling rather than nonzero conversion; numerical conversion is verified by host fixtures. Three served assets matched their package hashes. Production and the public installer were unchanged.


## Alignment marker placement feedback — September 24, 2026

Test bundle `833ff837e10db98cdceca8013b3995de7cd05da7918e67fd9708c15e87fd185d` adds two-marker overlap/boundary checks and measured center separation to the editor. The 25% image-diagonal suggestion is advisory, not a validated matching threshold. Draft feedback neither saves nor moves existing marker coordinates. Guidance padding and dark-theme button contrast are corrected.

79 host scripts, seven UI scripts and a clean ESP32 build passed. Browser review covered a 390px embedded editor, standalone light/dark rendering and numeric boundary feedback. Managed OTA/verified boot preserved configuration/profile/password, and four served files matched package bytes. Production and the public installer were unchanged. Automatic feature selection and third-marker support remain unfinished.


## Competing alignment peaks — September 24, 2026

Test bundle `31a3388e5eab85f826581187feae4b476a9726506cc17149f69dcfaa3c641339` rejects ambiguous local marker peaks rather than selecting one by scan order. Existing status numbers and rejected output state are preserved. Exact/near-duplicate host tests, 16 real-frame transform comparisons and 195 pipeline stress cases pass. Full packaging passed 80 host scripts, seven UI checks and a clean build.

OTA/verified boot preserved configuration/profile/password. The installed saved-image diagnostic matched all six dial tensors and outputs exactly in 13.946137 seconds; no camera captures or configuration changes occurred. This is a single compatibility/timing observation, not sustained capture cadence or independent accuracy validation. Production and the public installer were unchanged.


## Camera initialization readiness — September 24, 2026

Test bundle `8326f25fdb1ef0ff8c1aaa563ea74b30925fdc2be53b948ba617faeb6a51fa7e` clears previous readiness and sensor ID before camera initialization. A failed retry or missing sensor pointer cannot retain a stale ready state. The original driver error code is preserved; supported sensors and camera pins are unchanged.

The actual-method host fixture covers all three supported sensors, failed retries, missing and unsupported sensors, and recovery. Packaging passed 81 host scripts, seven UI checks and a clean ESP32 build. OTA/verified boot preserved configuration/profile/password, both served build metadata files matched the package, and one six-dial saved-image diagnostic retained exact tensor/output parity in 13.980167 seconds with zero camera cycles.

The board still reports camera unavailable. Its logs show repeated 0x105 address-probe failures; this deployment fixes stale state handling, not that underlying probe failure. The physical cause remains unresolved. Private evidence: `camera-readonly-audit-20260924/` and `aiedge-camera-init-state-01/` under firmware-port-tests. Production and the public installer were unchanged.


## Fixed radius reuse — September 24, 2026

Test bundle `40fd361540ff77eeaad5f096481563459a7e9de74236ba11cf42f68ddcfb607e`
reuses each dial's unchanged radius values across angles. All 81 host scripts,
seven UI checks and the clean build passed. Managed OTA/verified boot preserved
configuration/profile/password. Three paired saved-image trials retained exact
six-dial tensor/output parity and reduced median processing from 13.968 to
13.596 seconds. See [measurements and limitations](PERFORMANCE-MEASUREMENTS.md#reusing-fixed-radius-values--september-24-2026).
This does not resolve camera availability or establish live capture cadence.
Production and the public installer were unchanged.


## September 24: firmware missing-page response

Replaced the legacy ASCII-art 404 page with an AIEdge page using responsive spacing,
root-relative Overview and Device & maintenance links, and the existing browser theme
preference. Inline fallback styling remains readable if the shared theme script is
unavailable. Missing-page requests no longer change the page-selection cookie.
HTTP status and request-handler behavior are unchanged.

Test-board bundle `40bf77ff2b3406cd65e5eda767653261e4f713076685fb8a6ae63d3e2bfb516b`
passed the managed build and was installed by authenticated OTA. Post-restart reads
verified the complete compiled HTML response, HTTP 404 and HTML content type, home
page and shared theme script availability, preserved configuration/profile/password,
zero capture attempts and disabled archiving. The local comparison initially added
Windows line endings twice; normalizing compiler stdout fixed the verification
harness without changing firmware. Browser rendering remains unverified.
This is a test-board deployment, not a public installer release or production update.


## September 24: specific dial-preparation failure messages

Normal polar recognition now logs the dial name and failed preprocessing check,
including low contrast, low needle visibility, invalid crop transform, sampling
geometry, and feature extraction. A new attempt clears its diagnostic visibility
score before any early rejection, so an old score cannot describe a new failure.
Calculations, acceptance thresholds, fixed geometry, sampling and model are unchanged.

Bundle `9044f07d9a9bc3c83c87e93ea487d7dea669cef590844e500e2a95488a027317`
passed 84 host scripts, seven UI checks and the clean ESP32 build. Managed OTA and
verified boot preserved configuration/profile/password. One six-dial saved JPEG
replay matched all input tensors and outputs exactly in 13.680509 seconds, with
zero camera cycles and archival disabled. Host comparisons covered 120 preprocessing
cases with zero byte differences and 15 actual-flow checks. A public targeted test
covers malformed input, nonfinite transforms, dark/gray/white blank images and
stale-score clearing in both sampling modes. Failure branches were host-tested;
this was not a live bad-lighting capture test.

These messages identify failed checks, not physical root causes. Low contrast can
come from exposure, glare or obstruction; low needle visibility alone does not
prove retraining is needed. No automatic recalibration, model training, threshold
adjustment or lighting-change detector was introduced. Private evidence:
`aiedge-preparation-reasons-01/` under firmware-port-tests. Production and the
public installer release remain unchanged.


## September 24 — exact marker row accumulation

Test-board bundle `8cb6a276ad0b28f8d83acff9b76fd3ef2e1d48b10b4bd4c7fa610152e606c87f`
uses overflow-bounded 32-bit row sums with 64-bit marker patch totals. Model,
calibration and rejection gates are unchanged. Three saved-JPEG runs retained
exact tensor/output parity and reduced median processing from 13.645 to 11.662
seconds. See [measurements and limitations](PERFORMANCE-MEASUREMENTS.md).
85 host scripts, seven UI checks, clean build and managed OTA verification passed.
Configuration/profile preserved; zero camera cycles and no archival. Test board
only; live cadence, independent accuracy and public release remain outstanding.
