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
