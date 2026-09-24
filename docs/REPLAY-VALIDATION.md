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
with configuration and website password preserved. The 15-frame hardware
baseline has started; results remain pending.

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
ESP32 speed. The sparse sampler is isolated in experiment files and is not in
the deployed firmware. Broader image coverage and hardware timing are required
before adoption.
