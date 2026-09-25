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
| Installation and OTA | Recorded loader installation, authenticated application updates, reboot verification, and preserved configuration and website password. Latest test bundle: `cdd03e4a92bdeef837144695555343af3d6b69769e216eecf39c72b5d1b924f3`. | Repeated cold boots, power loss during flash writes, and physical missing/full-SD cases. |
| Interrupted updates | Restart during staging followed by successful retry on hardware, with interrupted files preserved. Index retry repair is deployed; 14 host index cases pass. | Hardware interruption during index publication and sudden-power-loss recovery. |
| Camera | An earlier single-image, no-flash preview succeeded. The latest test boot reports camera unavailable; the website and saved display profile remain usable. | Resolve the latest 0x105 camera address-probe failure first; its physical cause is unresolved. Then place the camera at the meter and verify calibration before live recognition. |
| Trained analog reader | Six-dial saved-image processing on ESP32 matches reference features and outputs. The separate reviewed-crop check passed 27/27 within 0.1 dial units. | Labeled full-frame camera validation across useful positions; the crop check reuses existing labels and has limited coverage. |
| Processing time | Latest three-image saved-JPEG comparison: 13.60-second median with exact reference parity (previous bundle: 13.97 seconds). Five normal-path SD surrogate cycles took 21.21–21.36 seconds at approximately 30-second start intervals; demo timestamps correctly remained invalid. | Sustained valid capture-to-publication cadence toward 30 seconds, including image storage and web use. |
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

Camera-independent profile startup is now installed and verified: with the camera unavailable, the compatible saved profile activates before HTTP starts. History display unit switching and restoration passed without restart or canonical-value changes. The test board has empty history; nonzero numerical conversions are host-tested.


## Frozen geometry reproduction — September 24

The local packaging workflow now regenerates the frozen geometry in memory and
requires byte-for-byte agreement with the active AIEdge calibration and identity
headers before a future candidate build. The exporter previously pointed at the
retired checkout; it now verifies `AIEdge-publication` by default. Optional output
requires a new folder and cannot overwrite existing files. Historical CRLF bytes
are preserved explicitly so the established calibration identity does not change
merely because generation runs on another operating system.

The verified geometry SHA-256 remains
`98ae8ce2c7f71176ace91c9b6c4f086a522e7da35a89140dea59cfd70d42096c`.
Three regressions cover exact active-header reproduction, changed geometry or
identity rejection, and separate-export overwrite refusal. Private source
artifacts are checked against the frozen reader manifest before generation.
Evidence: `geometry-reproduction-verified-20260924/geometry-export.json` under
firmware-port-tests. No firmware, model, geometry, accounting identity or live
setting changed. This gate covers the exported dial geometry and original two
marker templates; independent check-marker and preprocessing source validation
remain covered by their separate regression tests and package source hashes.


## Retrospective cross-dial screening — September 24

Seventeen retained full-frame images were rechecked for source/input hash
agreement, the frozen model identity, accepted alignment and unchanged recorded
imaging settings. Exact hashes were deduplicated; these are not seventeen
independent needle positions. The last main-dial pair exceeds the provisional
0.11 consistency bound in 14 images. Its signed residual ranges from -0.1280 to
-0.1094 (median -0.1157), while the last dial ranges from 3.2412 to 4.7741. The
other three main pairs pass in all seventeen images.

This points to a recurring relative offset in the observed range, not an isolated
frame failure. It does not identify which dial is responsible or distinguish
calibration, recognition bias and mechanical pointer offset. Historical outputs
share a model hash but are not asserted to share every preprocessing revision.
The next controlled comparison should use one frozen current preprocessing
pipeline and independently check printed tick positions and needle geometry.
Do not fit an offset to these protected observations or expand error bounds
merely to make them pass. No training or device change was made by this audit.

Private evidence: `cross-dial-retrospective-20260924/result.json` under
firmware-port-tests, including source-result hashes, per-pair signed residuals,
position ranges and limitations.


## Main-dial edge diagnostic — September 24

A retained-frame diagnostic compared the unchanged model with an existing
model-free, two-edge estimator, using the same frozen marker alignment and dial
calibration. Four images cover only two broad last-main-dial pose regions: three
nearly stationary estimates around 3.24–3.25, and one around 4.94. They do not
provide four independent positions or new accuracy labels.

For the fourth main dial, fixed-pivot and free-edge estimates differed by
0.158–0.202 dial units. On the latest last-main image, they differed by 0.438:
fixed-pivot edge estimate 4.968 versus free-edge estimate 4.530, in that dial's
numbering direction. The existing edge-agreement gate rejected that result.
The model estimate was 4.938. Shared calibration and uncertain edge geometry
mean these comparisons cannot identify which calibration or reading is correct.

Free-edge fitting is therefore not used to correct the recurring cross-dial
mismatch. The model, pivot, labels, consistency tolerance and firmware remain
unchanged. All source frames and derived crops are protected from training.
Private evidence: `main-pair-edge-audit-20260925/result.json` under
firmware-port-tests. Independent geometry/reading validation remains open.


## Rejected-observation publication fix (September 24)

The test board now runs bundle
`bcb755e540fdf1156da1f17549c9c4b17f310b8680234f1af7cf14554537e506`.
Accounting-rejected observations no longer become accepted analog ROI results;
the raw estimates and exact accounting reason remain available for diagnosis.
See the [bright-patch finding](IMAGE-PERTURBATION-VALIDATION.md#local-bright-patch-failure-and-publication-guard-september-24).

The clean build passed 86 host scripts and 9 interface scripts. The analog-source
harness covers 19 cases with 40 exact tensor comparisons; the controller harness
covers 27 cases. Authenticated OTA and restart verified the running bundle and
preserved configuration, display profile and website password. One post-update
saved-JPEG diagnostic took 11.708 seconds with six exact reference outputs and
zero camera captures. That diagnostic bypasses normal capture/accounting: it
checks installed inference compatibility, not a physical rejection test or live
capture cadence. The test camera still reports unavailable (0x105).

The model and calibration remain frozen. A recent unmodified image still exceeds
the adjacent-dial consistency allowance; the guard exposes that issue rather than
silently accepting it. Recognition/calibration work and real-image validation
remain necessary before replacing the operating meter reader.


### Fixed-pivot sensitivity diagnostic

On four protected full-image captures (only two broad last-main-dial pose regions),
the frozen desktop int8 reader was evaluated with temporary +/-1 and +/-2 pixel
needle-pivot offsets in each cardinal direction. The dial-face homography and
image pixels stayed fixed. The eight dial crops showed maximum changes of
0.0352–0.0432 dial units for one pixel and 0.0691–0.0879 for two pixels.
These are sensitivity measurements, not evidence that any offset is correct.

No offset was selected, no calibration or model was saved, and no evaluation
image entered training. The diagnostic used desktop dense features; it is not
an ESP32 sparse-path benchmark. Limited main-dial movement and the disagreement
between fixed/free edge fits prevent a reliable new pivot fit from these frames.
A correction must be supported by independent geometric evidence; merely making
adjacent numbers agree would hide rather than resolve the uncertainty.

Local evidence: `pivot-sensitivity-20260925/result.json`, with source/crop,
calibration, model and script hashes. All source frames and crops retain their
held-out exclusions.


### Accounting diagnostic freshness after rejection

The later test-board bundle `cdd03e4a92bdeef837144695555343af3d6b69769e216eecf39c72b5d1b924f3`
also publishes the optional accounting snapshot when polar recognition rejects a
frame. It does not resume normal reading publication or retry capture. The
[deployment record](DEPLOYED-IMPROVEMENTS.md#test-board-rejected-reading-accounting-diagnostics--september-24-2026)
distinguishes passing source-level transport tests and verified OTA from the
still-unverified physical broker-delivery test.
