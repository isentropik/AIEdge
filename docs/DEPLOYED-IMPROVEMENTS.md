# AIEdge deployed improvements

[Open improvement backlog](IMPROVEMENTS.md)

This archive records released changes and their actual evidence. It does not imply every feature has passed long-term testing. Local-only edits stay in the open backlog.

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
