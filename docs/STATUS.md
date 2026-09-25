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
| Installation and OTA | Recorded loader installation, authenticated application updates, reboot verification, and preserved configuration and website password. Latest test bundle: `7fe69f996ff2a14ee338fc5702fcf55ddbba2321ae6937033b2474737fb1ae6a`. | Repeated cold boots, power loss during flash writes, and physical missing/full-SD cases. |
| Interrupted updates | Restart during staging followed by successful retry on hardware, with interrupted files preserved. Index retry repair is deployed; 14 host index cases pass. | Hardware interruption during index publication and sudden-power-loss recovery. |
| Camera | An earlier single-image, no-flash preview succeeded. The latest test boot reports camera unavailable; the website and saved display profile remain usable. | Resolve the latest 0x105 camera address-probe failure first; its physical cause is unresolved. Then place the camera at the meter and verify calibration before live recognition. |
| Trained analog reader | Six-dial saved-image processing on ESP32 matches reference features and outputs. The separate reviewed-crop check passed 27/27 within 0.1 dial units. | Labeled full-frame camera validation across useful positions; the crop check reuses existing labels and has limited coverage. |
| Processing time | Latest routed-reader saved-JPEG trial: 15 files, 11.75-second median and 11.90-second maximum, with exact reference parity and no missed requested 30-second replay slots. Five normal-path SD surrogate cycles took 21.21–21.36 seconds at approximately 30-second start intervals; demo timestamps correctly remained invalid. | Sustained valid capture-to-publication cadence toward 30 seconds, including image storage and web use. |
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

The later test-board bundle `8cf81054ac5c39fc4b6f01b1a8e6e41d11a28409b0a12287d31636e03e341d50`
also publishes the optional accounting snapshot when polar recognition rejects a
frame. It does not resume normal reading publication or retry capture. The
[deployment record](DEPLOYED-IMPROVEMENTS.md#test-board-rejected-reading-accounting-diagnostics--september-24-2026)
distinguishes passing source-level transport tests and verified OTA from the
still-unverified physical broker-delivery test.


### Lighting-augmentation candidate not promoted

A separate fixed-schedule experiment reused only the original eight eligible
training images and 300 training-only synthetic derivatives. Half of sampled
profiles received randomized gain, gamma and a mild localized white overlay;
radial normalization was recomputed. The final checkpoint was selected by the
predeclared 35-epoch schedule, without evaluation checkpoint selection.

It passed 17/18 existing development examples within 0.1 versus the original
18/18. One secondary label of 4.3 produced 4.402356. Several moderate synthetic
lighting cases became more stable, but the severe second-main bright-patch
failure remained approximately 4.58 circular dial units. The candidate was not
exported or deployed. No label, tolerance, calibration or frozen model changed.

The robustness comparison used both float models on identical dequantized C++
sparse feature tensors. It is not candidate int8 or hardware validation. Prior
evaluation failures motivated the design; fresh independent evaluation would be
required before promotion. Current exclusion checks show no training/held-out
hash intersection, including synthetic parents. Local source hashes, training
regimen, results and decision: `needle-training/polar-lighting-candidate-20260925`.


### Same-capture linked-target experiment

An audit applied the unchanged C++ consistency rule to 22 unique retained
full-frame desktop estimates: 3 passed and 19 failed, all at the last two main
dials. One additional retained result was not evaluable. Unique image hashes
include nearly stationary poses; these counts are not independent accuracy
samples or complete sparse-firmware runs. Local evidence:
`retained-consistency-20260925-02/result.json`.

The original training capture's human labels were 0.3, 2.5, 5.6, 5.2, 3.0.
Its archived crop manifest and hashes identify the same device capture stamp for
all five main dials. A separate experiment preserved those original records and
used derived training targets 0.2553, 2.553, 5.53, 5.3, 3.0 from the 10:1
relationship. The last main dial remained the anchor; the secondary was not used
in that calculation. These are mechanically derived targets, not new human
labels or proof of perfect pointer phase alignment.

The fixed 35-epoch candidate retained 18/18 existing development checks within
0.1. On four protected main-dial pairs, spanning only two broad last-dial pose
regions, all four fit the unchanged 0.11 allowance. The latest pair's residual
fell from 0.12067 to 0.06182; the three earlier pairs fell to 0.00475–0.01070.
Both models used identical desktop dense features and unchanged calibration.

The candidate remains local and unpromoted. These development/consistency results
do not establish independent correctness, int8 parity, glare robustness or ESP32
performance. Evaluation labels and pixels were not used for gradients; prior
observed mismatch informed this experiment. Fresh validation and broader
regressions remain necessary. Exact provenance, derived targets, model and
results: `needle-training/polar-linked-target-candidate-20260925`.


### Linked-target int8 export and fixed routing

The candidate exports to 12,720-byte int8 TFLite with the same input/output
quantization, tensor shapes and operation set as the deployed model. Its 18-example
development check is unchanged; the largest float/int8 reading difference across
the export checks is 0.001656 dial units. This is desktop parity, not ESP32 proof.

The wider existing reviewed set gives 26/27 for the new model alone. A secondary
label of 8.1 predicts 8.20097 (original model: 8.11257), failing the unchanged 0.1
tolerance. Fixed routing by dial identity—candidate for all five main dials,
original model for the secondary—passes 27/27 reused reviewed crops. This routing
was chosen after observing that regression and is not independent validation.

On the retained 15-case synthetic lighting set, four cases remain rejected by
input checks. Of the eleven evaluated through reference int8 inference and the
existing C++ decoder/consistency rule, seven are mechanically consistent and four
are rejected, including the severe second-main bright patch. The unchanged
baseline's last-pair residual is 0.06698. Mechanical consistency is not accuracy,
and these cases informed development; no robustness guarantee is established.

The five-main-dial candidate and original secondary model are now deployed on
the test board with fixed role routing. Six-dial vector/RGB diagnostics matched
reference outputs, and 15 saved JPEG replays matched at a median of 11.75 seconds.
Both model hashes are required by the application before bundle selection.
Fresh independent accuracy evidence and live capture-to-publication testing
remain required before production promotion. Quantization used
only eligible training representatives. Local evidence: candidate `export/`,
`int8-all-confirmed-verification.json`, `routed-int8-reviewed-verification.json`
and `routed-stress.json`.


## Packages without private diagnostic images

The test board now boots a verified bundle without diagnostic images or vectors.
Both recognition models remain hash-verified and unchanged. The clean build
passed 91 host checks and 10 UI checks; managed OTA preserved configuration,
meter profile and website password. Requesting the omitted vector diagnostic
returned `fixture_unavailable`, completed zero dials and caused no capture,
restart or configuration change. It did not borrow the previous bundle's fixture.
Older bundles remain available for rollback.

This is a packaging and startup check, not a new recognition-accuracy result.
The public web installer remains on its September 22 development release.
This private development ZIP has not been published; its development metadata
needs a separate public-release review.
