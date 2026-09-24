# Real-image replay validation

The test board now supports a private held-out batch of 15 real meter JPEGs.
The diagnostic uses the current firmware decoder, alignment, preprocessing and
frozen model, and compares intermediate features and model outputs with the
host reference. Each JPEG and vector file must match its compiled SHA-256 and
length, and must resolve inside the verified running bundle. Private images and
reference binaries are not published in this repository.

Authenticated POST `/polar_jpeg_test?frame=0` selects the first frame; indexes
0 through 14 are supported. An empty POST to `/polar_jpeg_test` retains the
original single-image fixture. GET `/polar_jpeg_test` returns status and the
selected `replay_frame`; -1 means the original fixture. Malformed indexes, extra
query fields, request bodies and missing assets are rejected. Results are shared
with the RGB diagnostic, so clients must verify frame identity and boot identity.
Only one diagnostic runs at a time. Replay does not trigger the camera, feed
consumption accounting, publish meter readings or archive simulated captures.

Host tests cover all indexes, malformed requests, task admission, stale-result
reset, missing assets, memory cleanup and the original diagnostic. The ESP32
build passed. OTA installed bundle
`4a836c0789f993ffc70fd8f058235fafa776802f7541050d27c532f91a371e05`
with configuration and website password preserved. All 15 hardware baseline frames completed with exact feature/output parity.
Median processing time was 22.198651 seconds (range 22.118694-22.252863).
Boot identity and configuration remained unchanged. This excludes capture,
publication and archival and is not a 30-second live-cadence result.

These frames have retrieval timestamps, not reliable capture timestamps.
Retrieval order must not be used to calculate actual flow or missing complete
wheel revolutions. The frames remain excluded from training; model predictions
are reference outputs, not human ground truth or new accuracy evidence.

## Every-other-pixel experiment

A separate host-only experiment samples the even rows and columns with the
original bicubic kernel and fills the gaps by integer bilinear interpolation.
Crop dimensions, coordinates, frozen pivots, model and subsequent preprocessing
are unchanged. Across 15 frames / 90 dials, no visibility checks rejected, and
the maximum circular difference from full-resolution model output was
0.01040315 on the 0-10 scale. No comparison differed by more than 0.1.

This is agreement with the baseline, not verified accuracy. It does not measure
ESP32 speed. The sampler is now available as an opt-in preprocessing argument in local source;
existing callers retain full resolution. The diagnostic firmware contains the option,
and the selected test-board bundle now includes all 15-frame replay fixtures.
The opt-in implementation reproduced every feature byte of the isolated experiment
on all 15 frames. 243 synthetic crop/transform cases passed anchor, interpolation,
odd/even and single-pixel boundary checks. Dense-mode regressions retained exact
parity across 16 crop cases and 108 preprocessing cases. Broader image coverage
and hardware timing remain required before adoption.


## Sparse diagnostic selection

The diagnostic build accepts POST `/polar_jpeg_test?frame=0&sparse=1`.
It retains frame indexes 0-14 and returns `sparse_sampling: true` in the status.
Sparse reference vectors have separate compiled hashes and bundle files;
comparison with them tests execution parity, not agreement with dense outputs.
The host dense-versus-sparse reading comparison above remains a separate check.
At that test stage, normal processing was dense. Normal recognition later switched to sparse sampling in commit `2c954f7`; replay requests without `sparse=1` still use dense sampling.
The hardware batch is complete; results are recorded below.

## Large replay package staging investigation

The dense 15-frame baseline remains complete. The larger sparse-reference bundle
fails SD readback verification during staging; it has not been activated. The
card reports approximately 60 GB free. A preserved partial diagnostic vector file
was downloaded independently and matched the package byte-for-byte. Smaller
diagnostic firmware updates installed successfully with settings and password
verified unchanged.

Deferred error logging identifies a verification failure while the ZIP and its
indexes are still allocated. Resource pressure is a hypothesis, not a confirmed
allocator failure. The next candidate releases ZIP/index resources before the
independent full-tree readback. Extraction still validates length, CRC and SHA,
syncs and closes each file; full readback must succeed before publishing the
bundle. On the test ESP32, the updated stager successfully extracted and independently
verified the full 146-runtime-file replay bundle that previously failed. This
confirms recovery for that package; it does not identify the exact exhausted
resource or prove arbitrary package limits. Sparse timing results follow below.

## Completed sparse ESP32 replay

All 15 held-out full images (90 dial evaluations) completed on the test ESP32
with exact feature/output agreement to the separately generated sparse references.
Median processing time was **13.569199 seconds**, compared with the dense
baseline's **22.198651 seconds**: **38.87% less elapsed processing time**.
Sparse runs ranged from 13.311147 to 13.659937 seconds. Configuration was unchanged,
no camera cycles ran, and the diagnostic batch verified the same boot throughout.

These are saved-JPEG processing times, excluding camera/light acquisition, result
publication and archive upload. They do not establish live 30-second cadence or
reading accuracy. At that stage normal recognition was dense; commit `2c954f7` subsequently enabled sparse sampling in the normal path. The baseline and sparse runs
used different firmware builds; they used the same immutable image batch and
frozen model. Broader lighting/alignment and labeled-position coverage are still
needed before enabling sparse sampling for normal readings.

Mean crop-warp time summed across six dials: 11.915 seconds dense, 3.222 seconds sparse.

## Synthetic small-condition checks

The frozen host pipeline was tested on all 15 held-out full frames with identity,
0.85/1.15 global RGB gain, a 3-pixel right shift, a 3-pixel upward shift, and
+/-1-degree image rotations. Both dense and sparse modes were evaluated: 210
full-frame evaluations / 1,260 dial evaluations, including the identity controls.
Clean dense controls reproduced the existing reference feature/output bytes.
All transforms ran marker alignment before crop sampling; fixed calibrations and
needle pivots were unchanged. No alignment or visibility checks rejected.

Maximum circular change from each mode's clean reading was 0.015179 dense and
0.014770 sparse on the 0-10 dial scale. The two integer translations produced
exactly unchanged readings. Maximum dense-versus-sparse difference across the
cases was 0.010894; none exceeded 0.1. These are stability comparisons with model
outputs, not human-labeled accuracy.

Source and variant hashes, transform parameters, alignment matrices, model/header
hashes, feature bytes and output scores are preserved locally. All variants remain
excluded from training and share the held-out group of their parent image.
Uniform digital gain and image-plane rotation do not model physical glare, shadows,
camera exposure, tilt or parallax. Severe-change rejection and real lighting tests
remain to be done. No production setting changed.

## Severe rotation rejection gap and guard

A second synthetic suite found that black/white frames, Gaussian blur radius 6
and a 40-pixel horizontal shift were rejected, but a +10-degree rotation passed
alignment/visibility while the last main dial changed by up to 3.96 on the 0-10
scale. Both dense and sparse modes were affected. This is evidence that accepted
marker matches alone do not establish usable dial geometry/recognition.

The source now rejects automatic registration corrections exceeding 2 degrees.
This is a conservative operating boundary, not a proven accuracy guarantee inside
that range. A larger change requires checking the reference/calibration instead
of publishing a reading. Angle wrapping is handled; 36 synthetic boundary/wrap
cases passed and rejection leaves the output transform unchanged.

All 210 earlier small-condition frame evaluations retained exactly the same
acceptance, transforms and readings after the guard. In the severe suite, 150
perturbed frame evaluations were rejected and all 30 identity controls accepted.
This guard is host-tested only and is not yet deployed to the test board.

The standalone boundary regression is `tools/bundle-tests/rotation_guard_test.cpp`.
Compile with a C++11 compiler, assertions enabled, and include path
`code/components/jomjol_tfliteclass`. No private images are needed.


## Independent alignment check (September 23, local build)

A third fixed printed-label patch checks the original two-marker rigid transform without refitting it. The additional patch is at (108,76), size 48 x 24, in the frozen 640 x 480 reference, outside configured dial regions. Dial geometry, separate needle pivots and model weights remain unchanged. Firmware rejects weak third matches, near-collinear marker geometry or residual above a provisional three-pixel limit. The two-degree automatic rotation limit remains in force.

Actual C++ host checks across 195 saved image cases accepted 120 and rejected 75, matching the prior rotation-guard baseline. Accepted transforms remained unchanged to harness precision; failed checks left output untouched. These are reused development images, not independent accuracy validation. Identity images repeated across suites are not additional evidence. Focused tests cover disagreement, weak correlation, nonfinite inputs, collinearity, invalid tolerance and the residual boundary. The ESP32 build passed.

Test-board installation and added-check timing remain pending. Automatic proposals and generic three-marker setup are not available in the device UI yet. The additional compiled patch belongs to this meter-specific calibration.


The first third-marker test-board OTA attempt and one controlled retry after restart both failed during staging at the destination-object stat call (errno 5). The uploaded package was downloaded and its SHA256 verified before the retry. No firmware installation or boot selection occurred; the board remains on verified bundle `9f44b88823d269d5eb47ebe6be65ccfb9bbc71a3e3a06899157d71433a741999`. SD directory listings remain readable. This does not establish whether the cause is physical storage, driver behavior or resource pressure. No formatting or deletion of retained bundles was attempted. Third-marker hardware timing remains unmeasured.


USB diagnostics narrowed the repeated staging failure: `sdmmc_read_blocks failed (0x101)` preceded the destination stat error. In the installed ESP-IDF, 0x101 is `ESP_ERR_NO_MEM`; the SD read path allocates a DMA-capable temporary buffer when its destination is in external RAM. This is evidence of allocation failure, not evidence that formatting is needed.

The local stager now moves the parsed asset inventory and replaces its duplicate filename-to-ZIP-entry map with compact ZIP ordinals before SD operations. Manifest validation, per-file length/CRC/SHA checks, sync/close, independent full readback and boot-selection safeguards remain. The rebuilt C++ host harness passed 28 verifier, 19 boot-selection, 14 index, 8 transaction and 14 staging cases, plus readback of all 146 files in the actual candidate. Reversed archive ordering is covered. Physical-board recovery remains pending; this change is not yet a verified cure for the allocation failure.


### Test-board recovery and full-package retest

The 101-file recovery build installed and verified successfully, then the corrected stager processed the full 146-file package successfully. The full package staged in about 52 seconds; flash/boot selection took about 73 seconds. Boot verification confirmed bundle `2feca2abf39b0d94bd71d1a742ecbd48f40c0daa890e777afe8232a85310cbaa`, unchanged configuration and preserved whole-site authentication. No card formatting or retained-bundle deletion was used. This verifies recovery for this package and run; it is not a claim that all resource-pressure conditions are solved. The third-marker guard is now installed on the test board. Fifteen-frame hardware replay completed: every frame matched the saved sparse reference features and outputs exactly. Median processing was 14.358451 seconds (range 14.137257–14.432075), versus 13.569199 seconds in the prior sparse run: approximately 0.79 seconds added for the alignment guard. Configuration stayed unchanged, the boot identity remained stable and no camera cycles ran. These are replay timings, not capture/publication/upload cadence or independent reading accuracy.

## Saved-image replay validation

September 24, 2026. Test-board bundle `31a3388e5eab85f826581187feae4b476a9726506cc17149f69dcfaa3c641339`.

All 15 archived JPEG frames completed on the ESP32, with exact feature-tensor and output parity for all six dials per frame (90 dial outputs). The frames were replayed once in their existing order using sparse sampling. No new labels, training data or accuracy measurements were created.

The board retained the same boot identity and configuration throughout. The normal camera loop made zero attempts, the archive worker remained disabled, and no production device was accessed. This isolates saved-image recognition; it is not a sustained capture-to-publication or archive-overlap test.

### Processing time

| Stage | Median seconds | Maximum seconds |
| --- | ---: | ---: |
| JPEG decoding | 0.735 | 0.755 |
| Alignment | 3.967 | 3.990 |
| Six-dial preprocessing | 7.179 | 7.217 |
| Six-dial inference | 1.764 | 1.774 |
| Other diagnostic work | 0.347 | 0.362 |
| Total | 14.001 | 14.044 |

Total times ranged from 13.925 to 14.044 seconds. The nearest-rank 95th percentile is 14.044 seconds; with only 15 observations, it equals the maximum. Per-stage medians need not sum exactly to the median total.

All 45 diagnostic-status requests succeeded. Median latency was 203 ms, nearest-rank p95 was 328 ms, and maximum was 359 ms. These timings cover that status endpoint, not every website page or operation.

### Limits and remaining checks

Numerical parity verifies compatibility with the frozen reference pipeline, not physical reading accuracy. Similar/stationary dial positions are not independent accuracy evidence. Camera capture, lighting, MQTT publication, simultaneous image archiving, cold-boot behavior and sustained 30-second scheduling still need their own verification. The test board reported camera unavailable at preflight; the saved-image diagnostics remain usable in that state.

Private evidence: `needle-training/firmware-port-tests/aiedge-alignment-ambiguity-01/full-replay/`, including the preflight, per-run results and polls, final summary and timing analysis. The separate host ambiguity fixtures verify rejection of exact/near duplicate peaks; this normal replay batch did not inject ambiguous markers on the board.


## Controlled retained-frame consistency comparison — September 24

Seventeen retained full frames were processed again with one freshly compiled
current C++ decoder, alignment, crop/feature and output-decoder snapshot, and the
frozen int8 model using the TFLite reference interpreter. Input hashes were
verified against capture records; the headers match the current firmware source.
Both dense and sparse modes passed alignment and all six visibility checks on
every frame. This is a host comparison, not an ESP32 timing run.

The last main pair required review in 14/17 dense results and 17/17 sparse
results. Its signed residual was -0.12919 to -0.10870 in dense mode (median
-0.11550), versus -0.13478 to -0.11696 in sparse mode (median -0.12237). Sparse
processing shifts the fourth main dial by a median -0.00809 units relative to
dense, while the last main dial shifts by +0.00035. Three dense results just
below the 0.11 gate cross it with sparse sampling.

This rules out mixed historical preprocessing as the sole explanation of the
recurring discrepancy. It does not establish which prediction is physically
correct: these are model outputs, and unique hashes are not independent poses.
The sparse approximation contributes a small shift; dense processing already
has the larger inconsistency. Current normal recognition explicitly uses sparse sampling (commit `2c954f7`).
No sampling setting, threshold, calibration or model was changed by this comparison. Further work needs independent geometry or
needle evidence, not an offset fitted to protected outputs.

Private evidence: `controlled-cross-dial-20260924/result.json` and
`sampling-effect.json` under firmware-port-tests. The record includes executable,
native source/header and model hashes, per-frame features/scores and results.
