# AIEdge MVP

The first release targets the calibrated six-dial gas meter used during development.
It is not yet a general-purpose reader for arbitrary gas, water or electricity
meters. The priority is a usable replacement, followed by broader improvements.

## Included

- Frozen analog model, perspective compensation, marker alignment and visibility
  checks for the five main dials and secondary wheel. Digital OCR is not required.
- Raw dial positions kept separate from cumulative quantities. The secondary wheel
  is 5 cubic feet per revolution. Unknown or ambiguous intervals must not invent
  skipped revolutions or silently force a backward total forward.
- Authenticated website, camera/settings access and a selectable light/dark theme.
- OTA installation with configuration preservation and an available USB recovery path.
- Optional queued HTTPS image uploads to a receiver on a storage server. The server
  selects the folder. Archived images remain unreviewed, outside model training.
- A 30-second capture interval as a target. Report rejected frames, missed slots and
  actual timing; use a longer interval if successful processing cannot keep up.

## Evidence already available

The test board runs the custom firmware. OTA and configuration preservation have
passed. A queued JPEG has reached an HTTPS receiver with its hash verified.
Twenty-seven reviewed crops pass the existing tolerance, and three estimates from
one full image have been confirmed. A current saved-image ESP32 replay processes
all six dials in 14.31 seconds with exact reference feature/output parity.

Five real camera cycles on an unrelated scene maintained approximately 30-second
spacing and remained responsive. Those cycles correctly rejected the scene and
are not evidence of successful live meter throughput. The test camera is still
viewing a different scene, as confirmed by the user.

A newly retrieved production-meter cached image still matches the saved imaging
configuration and passes the frozen desktop alignment/visibility checks. The user confirmed its fourth and fifth main dials as 5.3 and 4.5; the
secondary remains unconfirmed. The small last-two-main-dial consistency warning
remains visible. Its
retrieval time is not a verified capture timestamp. It remains excluded from training.

## Before replacing the operating reader

1. Verify the candidate on a current meter image, including any consistency warning.
   Keep unresolved readings visible as estimates or unknown rather than silently
   changing calibration or labels.
2. Preserve the operating device's configuration and recovery image. Prepare an
   exact migration that retains its network/publication identity, units and history.
3. Perform a bounded live meter run with the correct geometry. Verify readings and
   receipt at the publication destination. Measure actual successful-cycle timing;
   30 seconds is a goal, not a release claim based on rejected images.
4. If optional archiving is enabled for that run, verify delivery and that a failed
   receiver does not prevent continued meter operation.

These steps are the MVP acceptance work. The production meter has not been changed.

## Follow-up work

Broader meter support, automatic marker suggestions, extensive lighting augmentation,
exhaustive power-interruption/full-card testing and performance tuning beyond the
useful cadence target belong to follow-up work. Existing failures that threaten
readings, data integrity, installation or recovery still need fixing before release.

See [release evidence](RELEASE-READINESS.md) and the [improvement backlog](IMPROVEMENTS.md).

## Agreed commissioning route

Continue with saved images and surrogate sequence files first. The planned live
transition is a clean installation of the complete stack on the operating unit,
wiping its flash and SD card after the useful surrogate tests are complete.
No wipe has been performed. Preserve the existing configuration, calibration,
network/publication identity and recovery material before that operation; a
config.ini copy alone is not a flash/SD backup. Clean installation also requires
Wi-Fi and first-time website-password setup.

The actual analog readout conversion now passes checks for leading zeros, tenths
truncation, following-dial carries, decimal scaling and invalid-result rejection.
Local consumption/session regressions also pass for jitter, rollovers, missing
frames, restart gaps and ambiguity. These are not live-publication measurements.

[Saved-image perturbation tests](IMAGE-PERTURBATION-VALIDATION.md) now cover
brightness, translations and rotation with the frozen reader. These supplement
the real-image reviews without counting synthetic variants as new accuracy data.
