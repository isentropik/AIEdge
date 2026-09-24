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
