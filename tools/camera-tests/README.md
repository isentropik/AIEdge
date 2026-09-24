# Camera capture regression

Run with Python 3 and a C++ compiler:

```sh
python test_capture.py --cxx c++
```

Alternatively, use `--zig-python /path/to/python` for an interpreter with
`ziglang` installed. No dependencies are downloaded by this script.

The test compiles the actual `CaptureToBasisImage` function with simulated camera,
JPEG decoder, clock, lighting and logging boundaries. It checks all 921,600 RGB
bytes for a 640x480 frame, as well as invalid buffers, geometry, lighting failures,
missing camera frames, failed decoding, demo timestamps and future/invalid clocks.
It does not contact a device and does not measure ESP32 memory speed or accuracy.

## Rotation traversal parity

Run `python test_rotation.py --cxx c++` (or the same `--zig-python` option).
It compares production rotation, antialiased rotation and translation against
`rotation-baseline.cpp`, the preserved implementation from AIEdge commit
5872a1b, inherited from jomjol/AI-on-the-edge-device under this repository's
license. This technical test reference retains the upstream implementation;
it is not an original AIEdge algorithm.

The 480 comparisons cover RGB/grayscale, 13x9, 144x146 and 640x480 buffers,
positive/negative/zero/right-angle rotations, flips and both temporary-buffer
paths. Every output byte and resulting geometry must match. Host math/memory
checks do not measure ESP32 cache performance.

## Normal recognition failure handling

Run `python test_normal_recognition.py --cxx c++` (or `--zig-python`).
The harness compiles the actual `ClassFlowCNNPolar.cpp` control flow, using the
real frozen dial geometry and simulated model, alignment, preprocessing, preview
and accounting boundaries. It exercises successful publication, model/allocation
failures, every dial's preprocessing/inference/preview failures, missing or
changed image geometry, missing/extra/reordered ROIs, and a failed frame following
a successful frame. During processing, all six public results must remain rejected
and NaN; accounting must receive no observation unless every dial succeeds.

This checks control flow, not model accuracy, allocator capacity, camera behavior
or timing on the ESP32. Fault fixtures do not substitute for a sustained valid
capture-to-publication hardware run.

## Analog readout conversion

Run `python test_analog_readout.py --cxx c++` (or `--zig-python`).
This compiles the actual analog branch of `getReadout`, `PointerEvalAnalogNew`
and `ShiftDecimal`. It checks the current saved-image estimates, leading zeros,
tenths truncation, following-dial carry handling, main decimal scaling, the
separate legacy secondary position, and rejected/nonfinite/out-of-range values.
The fixtures do not exercise all postprocessing, MQTT delivery, or UI formatting.

## Saved-reading recovery

`test_saved_readings.py --zig-python /path/to/python-with-ziglang` compiles the
actual `LoadPreValue` and `SavePreValue` methods. Temporary files cover valid
current and legacy formats, empty files, missing fields, malformed numeric or
timestamp values, and descriptor closure. Injected open/write/close failures
verify that failed saves retain the pending-write flag. This prevents startup
crashes and false successful saves; it does not make the legacy file update
atomic or prove physical SD durability.
