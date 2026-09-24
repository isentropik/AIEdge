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
but its currently selected small bundle omits the 15-frame replay fixtures.
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
Normal meter processing and requests without `sparse=1` remain dense.
Sparse hardware timing is pending until deployment and the batch finish.

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
bundle. Hardware validation of this change and sparse timing remain pending.
