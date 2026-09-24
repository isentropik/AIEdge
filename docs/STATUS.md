# Development status

[Back to AIEdge](../README.md) · [Installation](INSTALLATION.md) · [Glossary](GLOSSARY.md)

Updated September 23, 2026 (Pacific time). **AIEdge runs on the test board, but is
not yet verified as a replacement for the operating meter reader.** The production
meter has not been changed by these test-board deployments.

The [MVP scope](MVP.md) defines the first usable release and separates follow-up
work from the remaining production-migration checks.

## What has been verified

| Feature | Current evidence | Still needed |
| --- | --- | --- |
| Installation and OTA | Recorded loader installation, authenticated application updates, reboot verification, and preserved configuration and website password. Latest test bundle: `58e442c75990fe2b31e16fabde18f86482dc883b52da3574c481e09ee504502f`. | Repeated cold boots, power loss during flash writes, and physical missing/full-SD cases. |
| Interrupted updates | Restart during staging followed by successful retry on hardware, with interrupted files preserved. Index retry repair is deployed; 14 host index cases pass. | Hardware interruption during index publication and sudden-power-loss recovery. |
| Camera | A fresh single-image, no-flash preview succeeds on the current test firmware. | The test camera currently sees room furnishings, not the meter. Place it at the meter and verify calibration before live recognition. |
| Trained analog reader | Six-dial saved-image processing on ESP32 matches reference features and outputs. The separate reviewed-crop check passed 27/27 within 0.1 dial units. | Labeled full-frame camera validation across useful positions; the crop check reuses existing labels and has limited coverage. |
| Processing time | Latest saved-JPEG replay took 14.31 seconds with exact reference parity. | Sustained valid capture-to-publication cadence toward 30 seconds, including image storage and web use. |
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
