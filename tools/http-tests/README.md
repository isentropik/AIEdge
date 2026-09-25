# Reading endpoint regression

Run `python tools/http-tests/test_empty_readings.py` with a C++11 compiler on PATH,
or pass `--cxx PATH`. For Python with ziglang, pass `--zig-python PATH_TO_PYTHON`.

The test compiles the actual all-readings branch from MainFlowControl.cpp with
stubbed flow output and HTTP transport. It verifies exactly one completed response
for empty and nonempty output, unchanged response bytes, all four reading types,
and propagation of transport failure (16 cases). It does not execute the complete
HTTP server or request-query parser. No device is contacted.
