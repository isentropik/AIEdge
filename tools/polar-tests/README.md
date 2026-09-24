# Polar preprocessing checks

`percentile_test.cpp` checks the two order statistics used by the frozen
75th-percentile background calculation against full sorting. It covers 12,000
arrays with fractional, repeated, constant, ordered and isolated-outlier data.
Run from the repository root with a C++11 compiler and assertions enabled:

```
c++ -std=c++11 -O2 -ffp-contract=off -UNDEBUG -Icode/components/jomjol_tfliteclass tools/polar-tests/percentile_test.cpp -o percentile_test
./percentile_test
```

This is an exact-value regression, not an ESP32 speed benchmark or recognition
accuracy test. Private full-image fixtures are deliberately not distributed.

`cubic_bytes_test.cpp` compares the byte-input cubic helper with the original
double-coefficient expression. It checks 200,000 deterministic byte tuples at
six boundary/fixed fractions plus a randomized fraction (1,400,000 comparisons),
and all 16 extreme-byte tuples at the six fixed fractions. Results must match
bit-for-bit, with fused contraction disabled as in the firmware build:

```
c++ -std=c++11 -O2 -ffp-contract=off -UNDEBUG -Icode/components/jomjol_tfliteclass tools/polar-tests/cubic_bytes_test.cpp -o cubic_bytes_test
./cubic_bytes_test
```

The helper uses exact integer coefficients only for the horizontal pass whose
inputs are bytes. The vertical pass still uses the original double arithmetic.
It preserves interpolation, edge handling and output clipping. Passing this
regression does not establish an ESP32 performance improvement.

`preparation_status_test.cpp` checks that malformed geometry and blank images
retain distinct failure reasons in both sampling modes, and that an earlier
visibility score cannot survive a new rejected attempt. Compile as above with
`preparation_status_test.cpp` as the input. These reasons identify failed checks,
not a proven physical cause: low contrast does not by itself mean the LEDs failed,
and low needle visibility does not automatically mean the model needs retraining.
