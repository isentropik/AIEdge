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

Three full-frame dial reviews are pending. Their model estimates are not labels,
and those source frames and review derivatives remain excluded from training.
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
