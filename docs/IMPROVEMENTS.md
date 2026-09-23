# AIEdge improvement backlog

Updated September 23, 2026 (Pacific time). This is the running list of open work. Deployed items move to the [deployment archive](DEPLOYED-IMPROVEMENTS.md); they do not remain as completed rows here. Partially completed items describe only the remaining work. A local build is not a deployment.

## Installation and recovery — highest priority

| Item | Current state | Done when |
| --- | --- | --- |
| Managed OTA staging failure | September 23 authenticated test upload matched the local ZIP hash, but staging returned `storage_error` with a zero-byte `image-archive-settings.js` after earlier files were extracted. Firmware was not installed and boot selection was unchanged. Pending files are retained. An uncompressed ZIP subsequently completed authenticated OTA, restart and password/configuration retention. A second compressed staging-only trial reproduced the failure at the same file; USB recording confirmed SDMMC error 0x101 (ESP_ERR_NO_MEM): a 1,672-byte read returned 543 bytes and errno 5. SD log writes failed at the same time, hiding the read diagnostics. A PSRAM-only ZIP allocator is built and under test; compressed hardware verification remains pending. | Diagnose from on-device failure evidence and complete authenticated staging, installation, restart and USB-boundary verification with configuration/password retention. |
| Installation reliability across retries and interruptions | A truncated-download rejection, restart, retry and complete installation now pass on hardware; power-loss interruption coverage remains incomplete. Deployed individual repairs are in the archive. | Repeated installations, retries and interruption tests pass with preserved configuration and useful failure messages. |
| Prevent stale installer tabs from flashing an old release | Observed: an open tab still offered 0.1.8 after 0.1.10 publication; board identity also reported 0.1.8. Refresh corrected the page. Local release-watcher and controller integration tests now pass: expired clicks, offline retry and superseded releases preserve verified bytes and active dialogs. Publication pending. | Show the verified image version prominently and detect a superseded image before installation without disrupting an active flash. |
| Insufficient SD space | Local implementation, boundary tests and final loader build pass, including retry after a capacity failure. Test loader deployed to the test board only: sufficient-space check passed (11,108,352 required; 63,810,945,024 available). Full-card/retry cases and public release remain pending. | Before downloading, check actual FAT allocation size and free clusters against the pinned ZIP, extracted files, metadata and reserve. Show required/available bytes; allow safe retry; never delete user files. Test a genuinely full card. |
| No SD card / unsupported filesystem | Local firmware-resident recovery builds successfully. It reuses saved loader Wi-Fi, provides a read-only recovery hotspot, and preserves NVS on initialization failure. Credential compatibility and page tests pass. Installed on the test board; physical no-card boot remains untested. | Serve a firmware-resident recovery UI with actionable status and saved Wi-Fi, even without SD. |
| Optional SD formatting | Requested as a capability; not implemented or authorized to execute on this board. | Provide an explicit destructive confirmation; never format automatically. |
| Faster USB installation | Current public installer tries 460,800 then 115,200 baud. September 23 full-flash backup encountered corrupt serial data at 460,800 before any write; slower recovery attempt is recorded separately. This does not establish a universal maximum baud rate. 921,600 and 1,500,000 remain untested. | Measure complete flash time and verify integrity/reliability at faster speeds; retain bounded slower fallback. |
| Wi-Fi scan responsiveness | Full scan results returned together, with a 15-second failure timeout. | Measure actual scan and USB response durations; improve progress feedback and consider recent-result caching. Shorter scan timings must retain network discovery reliability. |
| Saved Wi-Fi and reconnection | A later boot failed to reconnect. A bounded saved-network retry is now installed in test loader 0.1.11-test2; its next boot connected successfully. Forced-disconnect recovery remains untested. | Repeated cold boots and USB reconnects recover without asking for credentials again. |
| Hostname discovery | Unique aiedge-MACsuffix name configured; LAN resolution remains to be tested across clients. | Both IP and advertised .local URL work reliably, with an IP fallback shown. |
| Download progress and diagnostics | Bytes/speed/progress and bounded USB/RAM diagnostics implemented. | Verify stalled/offline/reboot states and remaining-time accuracy; retain useful diagnostics after failure where feasible. |
| OTA and interrupted-update recovery | Legacy updater bypass now blocked in managed builds; dual-mode guard tests and ESP32 build pass; installed on the test board. Versioned bundle verification/staging implemented locally; full recovery guarantees unproven. | Test power loss, bad images, SD removal and reboot selection on hardware. |


## Consistent interface and branding

| Item | Current state | Done when |
| --- | --- | --- |
| AIEdge branding throughout | Local source edits cover error/setup pages, logs/config labels, MQTT manufacturer and build name. Firmware build passed. | Audit every product-facing page and generated response; package and verify the changes. Preserve upstream copyright, credits, historical links and compatibility identifiers where required. |
| Matching GUI on every page | Shared styling installed on the test board; normal camera-absent homepage verified. Remaining pages and mobile interactions need review; public release pending. | Overview, camera/ROI tools, settings, logs, updates, setup and recovery share navigation, typography, spacing, controls and mobile layouts. Check real data and all interaction states. |
| User-selectable theme everywhere | Main pages support system/light/dark; self-contained error-page theme added locally. | Theme choice persists and matches across top-level pages, iframes, loader and recovery, including unavailable-SD state. |
| Original visual assets and beginner-friendly instructions | Setup introduction rewritten and inherited promotional images removed locally. Broader audit pending. | No copied promotional visuals; original assets and clear steps, with upstream technical attribution retained. |
| Preserve ROI geometry while restyling | Shared style deliberately leaves intrinsic canvas coordinates unchanged. | Verify marker placement, pointer mapping, scaling and saved coordinates on desktop and mobile. |

## Meter recognition and physical calculations

- [ ] Extend the passing full-RGB-frame ESP32 registration/preprocessing/inference parity test to actual camera capture/JPEG decoding and confirmed real-image accuracy; preserve held-out data, raw hashes and uncertain labels.
- [ ] Validate perspective compensation, stable dial/needle pivots and glare-sensitive edge estimates across positions.
- [ ] Cross-check the main sequence using subsequent dials; preserve leading zeros and separate raw dial positions from converted quantities.
- [ ] Reconcile the 5 ft³ secondary revolution with the final main dial: 20 revolutions per numbered step, 200 per full main-dial revolution.
- [ ] Handle rollover, jitter, missing frames and restart gaps without inventing complete turns; flag ambiguous/backward cumulative totals.
- [ ] Measure sustained valid capture-to-publication cadence toward 30 seconds, including UI and archive traffic. [Short hardware comparison](PERFORMANCE-MEASUREMENTS.md): fixed-frame processing median 26.943 seconds at 160 MHz and 18.245 seconds at 240 MHz, all bytes matching; this excludes the full live cycle. Record timing distributions, missed captures and memory margins.

## Lighting, storage and configuration

- [ ] Provide explicit recovery/management of retained destination and legacy unbound queues. The deployed setup UI explains retained queues; credential-change isolation and recovery pass on the test board. Broader storage-limit and destination-change hardware coverage remain open.

- [ ] Verify all 19 SK6812 RGBW pixels, byte order, dedicated white-only output and master brightness at 0, 1, intermediate and full levels on hardware.
- [ ] Make capture, preview and live-stream illumination consistent; allow responsive intensity changes without exposing an in-flight recognition capture to mixed settings.
- [ ] Broaden optional image-archive coverage for receiver compatibility, rejected credentials, storage limits, sustained retries and physical power interruption. The settings UI/API, stale-save rejection and recovery from simulated torn files now pass on the test board. Queued-image HTTPS delivery already passed. A real user storage server is not required to configure this optional feature; the receiver controls its destination folder.
- [ ] Apply routine settings immediately or at a safe cycle boundary; distinguish saved, active, pending and failed states. Validate rollback on rejected changes.
- [ ] Verify MQTT/HA reporting, units and freshness separately; no silent entity-ID or historical-total migration.

## Evidence and update rules

- Update this file as issues are found, prepared and tested. Move deployed items to the archive with version and evidence. Keep unresolved failures and limitations here; deployment alone does not prove all acceptance checks passed.
- The September 22 installation pass did not validate camera capture: the test camera was disconnected.
- Latest local USB evidence for the old-loader recurrence: `recorded-20260923T065212Z`; successful 0.1.10 installation: `recorded-20260923T063329Z`. Evidence is stored privately under the workspace's `needle-training/firmware-port-tests/aiedge-setup-diagnostics/`.
- See [development status](STATUS.md), [implementation roadmap](../IMPLEMENTATION-ROADMAP.md), and subsystem status files for detailed requirements. This list does not reduce the original firmware/model/performance/archival objective.

## Remaining verification after the September 23 test deployment

- Finish interaction checks on every page, including camera/alignment editing and mobile setup completion. Read-only phone-width checks and served-asset hashes are not a substitute for saving and reloading each setting.
- Finish in-app Wi-Fi editing; the current network page reports connection details and points to USB configuration.
- Test actual power loss during update, physical no-card/full-card behavior, and repeated Wi-Fi recovery. Download interruption recovery has passed; other cases are not implied.
- Complete public release packaging after these remaining checks. The public installer is unchanged.

Completed camera, analog-only, UI, download-retry and journaled-save changes are recorded in the [deployment archive](DEPLOYED-IMPROVEMENTS.md).
