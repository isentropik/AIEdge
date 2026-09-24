# Development status

[Back to AIEdge](../README.md) · [Installation](INSTALLATION.md) · [Glossary](GLOSSARY.md)

Updated September 24, 2026 (Pacific time). **AIEdge runs on the test board, but is
not yet verified as a replacement for the operating meter reader.** The production
meter has not been changed by these test-board deployments.

The user has requested continued improvement and review beyond the original MVP
cutoff. The [running backlog](IMPROVEMENTS.md) tracks that work. Production
migration remains deferred while saved-image and test-board testing continues.

## What has been verified

| Feature | Current evidence | Still needed |
| --- | --- | --- |
| Installation and OTA | Recorded loader installation, authenticated application updates, reboot verification, and preserved configuration and website password. Latest test bundle: `47d72cb445c39b72c061331b5c2f75b17d727e24ea3e66e9dbb34e31fa519e45`. | Repeated cold boots, power loss during flash writes, and physical missing/full-SD cases. |
| Interrupted updates | Restart during staging followed by successful retry on hardware, with interrupted files preserved. Index retry repair is deployed; 14 host index cases pass. | Hardware interruption during index publication and sudden-power-loss recovery. |
| Camera | A fresh single-image, no-flash preview succeeds on the current test firmware. | The test camera currently sees room furnishings, not the meter. Place it at the meter and verify calibration before live recognition. |
| Trained analog reader | Six-dial saved-image processing on ESP32 matches reference features and outputs. The separate reviewed-crop check passed 27/27 within 0.1 dial units. | Labeled full-frame camera validation across useful positions; the crop check reuses existing labels and has limited coverage. |
| Processing time | Latest saved-JPEG diagnostic: 14.29 seconds with exact reference parity. Five normal-path SD surrogate cycles took 21.21–21.36 seconds at approximately 30-second start intervals; demo timestamps correctly remained invalid. | Sustained valid capture-to-publication cadence toward 30 seconds, including image storage and web use. |
| Remote image storage | Optional queue and HTTPS receiver implemented; a recorded image delivery passed. Host tests cover failed connections, rejected credentials, receipts and receiver interruption. | Physical outage/retry and SD power-loss tests, storage limits, and sustained operation. |
| Website access | Whole-device password protection deployed. Thirty read-only route checks passed across protected and authorized requests. | Broader interaction and browser behavior review. |
| Interface and lighting | Shared interface and RGBW support implemented; several pages and assets verified on the test board. | Every page on mobile, all 19 RGBW pixels, and live brightness behavior on the installed strip. |

Saved-image timing excludes camera acquisition and result publication. Matching
reference output demonstrates port consistency, not independent accuracy.
Unlabeled predictions, fast rejected frames and repeated stationary views do not
establish the live-reading target.

## Before a live meter trial

1. Position the test camera so the entire meter face and alignment markers are visible.
2. Review a new image against the frozen reference: resolution, rotation, marker
   positions, all six dial crops and their directions must agree. A moved camera
   may require a new calibration; do not bypass geometry rejection to start a run.
3. Confirm readings from real images, keeping trial images out of training.
4. Measure capture timestamps, accepted readings, missed captures, web latency
   and image delivery over a sustained run. Report failures as well as successes.

The original installation observations are historical, not the current board
state. See the [deployment archive](DEPLOYED-IMPROVEMENTS.md) for individual
repairs and the [open backlog](IMPROVEMENTS.md) for remaining work.

Supporting evidence: [reviewed crop check](REVIEWED-CROP-VALIDATION.md),
[saved-image timing](CROP-TIMING-TRIAL.md),
[image delivery behavior](IMAGE-ARCHIVE-FAILURES.md), and
[cadence trial instructions](../tools/cycle-trial/README.md).

The newest private camera check is
`needle-training/firmware-port-tests/camera-readiness-20260924T011245Z/result.json`.
Its image is excluded from training and is not published in this repository.

## Saved-reading recovery update

The September 24 test-board update preserves the prior in-memory readings when any row of the saved-reading file fails to load. A valid first row followed by a malformed second row no longer leaves partially loaded values active. The regression compiles the actual loader and checks values, formatted strings, timestamps, validity flags and pending-save state. The clean ESP32 build and 78 packaging checks passed.

Managed OTA and restart verification passed with configuration, meter profile and password preserved. All 146 runtime assets were retained byte-for-byte; six served routes were checked, including the configured setup-mode index route. A post-install six-dial saved-JPEG replay matched reference features and outputs exactly in 14.267908 seconds. This is port-regression evidence, not new labeled accuracy or live capture cadence.

Private evidence: `needle-training/firmware-port-tests/aiedge-transactional-readings-06/{ota,replay-smoke,served-assets.json}`. The general build-checkout package was rejected before installation because its older HTML would regress the UI; the installed package preserved the verified modern assets. Future packaging now takes an explicit modern UI source and guards its hashes separately from firmware sources.

## Strict saved timestamps

The next September 24 update validates calendar dates and time fields before accepting saved readings, honors stored UTC offsets, and never treats future timestamps as fresh. Host regressions reproduced the previous acceptance of February 30, then passed strict date, leap-year, offset-equivalence, future-time and rollback cases. Offset-free legacy files retain local-time interpretation; an incorrect system clock and ambiguous local timestamps without offsets cannot be repaired by this parser.

The ESP32 build and managed OTA/boot checks passed with configuration, profile and password preserved. All runtime assets and the recognition model are unchanged. Timestamp behavior is verified in actual-loader host tests; no new real-meter accuracy claim or hardware clock-fault test is implied. Private evidence: `needle-training/firmware-port-tests/aiedge-strict-saved-times/{validation.json,ota/result.json}`. The earlier title-encoding concern was a diagnostic decoding error: raw served UTF-8 bytes were correct.

Current test-board issue: a camera-unavailable boot skips flow initialization, which also skips saved display-preference activation. The profile remains preserved but pending. Separating profile startup from recognition is required; the history-unit device trial stopped before any profile write.
