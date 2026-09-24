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
