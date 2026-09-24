# Release readiness

AIEdge is running on the development board. It is not yet a verified replacement
for the production meter. This is an evidence inventory, not a release approval.

| Requirement | Evidence | Still needed |
| --- | --- | --- |
| Analog recognition and training protection | 27 protected human-reviewed crops pass within 0.1; original labels/hashes rechecked | Human-reviewed full images through alignment and firmware recognition; broader independent evidence |
| Capture every 30 seconds | Capture and alignment optimizations installed and individually measured | Sustained valid capture-to-publication run with UI and archival traffic; rejected scenes do not count as successful cycles |
| Cumulative consumption | Rollover-aware accounting and ambiguity handling implemented/tested | Physical sequence and restart-gap verification without invented secondary turns |
| OTA | Multiple recorded test-board installs preserve configuration and authentication | Physical interruption/recovery coverage and production migration verification |
| Remote training-image storage | A queued 21,723-byte JPEG was delivered over ESP32 HTTPS with verified receipt; images remain unreviewed | Sustained upload/inference overlap, unavailable/full receiver, resource margins and recovery |
| Usable replacement firmware | Test board boots with camera, modern interface and device authentication | Remaining setup/UI review and verified production reporting |

Three dial estimates from one held-out full image were confirmed by the reviewer.
These are confirmations of displayed estimates, not independent precision
measurements. The source frame and review derivatives remain excluded from training.
A fresh test-board replay of that saved JPEG completed all six dials in 14.31 seconds
with exactly matching feature and inference-output bytes. This diagnostic releases
image storage before inference allocation; it does not verify the normal capture
path, simultaneous memory use, or sustained capture-to-publication cadence.
Nearby crop timestamps cannot supply labels for cached full images with unknown
capture time.

The local audit now recomputes crop pass counts from protected label records,
checks raw image/model/calibration hashes, and records source evidence hashes.
It rejects duplicated results, changed label provenance, altered image bytes,
training overlap and false pass flags. Eight audit regressions pass. Historical
model-only acceptance does not mean this complete firmware project is finished.
Recorded deployment evidence is explicitly distinguished from a fresh device check.

See [reviewed crops](REVIEWED-CROP-VALIDATION.md),
[camera timing](CAMERA-COPY-VALIDATION.md),
[alignment timing](ROTATION-TRAVERSAL-VALIDATION.md),
[archive timeout](ARCHIVE-UPLOAD-DEADLINE.md), and the
[remaining improvement backlog](IMPROVEMENTS.md).

The actual normal recognition control flow also passes host fault injection:
model/allocation/alignment failures, per-dial preprocessing/inference/preview
failures, geometry changes, and stale results after an earlier successful frame.
No failing case publishes partial readings or advances accounting. These checks
use dependency fixtures and do not establish ESP32 memory capacity or timing.
See [normal recognition tests](../tools/camera-tests/README.md#normal-recognition-failure-handling).

## Short camera scheduling trial

A five-cycle test on the development board used a 30-second interval, LEDs off,
and no external publication or image archiving. The camera deliberately viewed
a scene other than the meter. All five cycles captured and completed the legacy
alignment stage, then failed meter-marker registration; none produced an accepted
reading. No overlapping attempts or missed schedule slots were reported.

Four capture intervals had a 30.008-second median and 30.028-second maximum.
Across 23 timing-endpoint polls, response latency was 0.187 seconds median,
0.266 seconds p95, and 0.406 seconds maximum. This measures only that endpoint
under this short rejected-scene workload. It does not prove the performance of
successful six-dial recognition, publication, image upload, or other web pages.

The original configuration was restored byte-for-byte and the saved meter profile
was preserved. Successful live-meter cadence remains unverified while the test
camera views a different scene.

## Saved-reading recovery update

The test board now runs bundle
`dcff21d1e6ddfa15888dbccb28b9401929245760323b6dd78d2aecd35877a0e4`,
which contains the saved-reading recovery fix. The recorded OTA verified the
new running bundle and preserved configuration, meter profile and website
authentication. A post-update saved-JPEG replay completed all six dials in
14.253834 seconds with exact feature/output reference parity, unchanged settings
and zero camera cycles. This remains a diagnostic replay, not a measurement of
live capture-to-publication cadence. The production device is unchanged.

Actual-source host tests reject missing fields, invalid numeric values and
malformed timestamps; empty files close cleanly. Failed open/write/close tests
retain the pending-save flag. This does not make the legacy saved-state file
update atomic or establish physical SD power-loss durability.
