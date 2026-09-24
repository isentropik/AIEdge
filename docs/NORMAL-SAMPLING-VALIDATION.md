# Normal recognition sampling

The normal PolarV1 capture path now explicitly uses the same even-grid bicubic sampling and integer interpolation checked in saved-image ESP32 replay. It retains the frozen crop coordinates, needle pivots, model, three-marker alignment guard and visibility checks. Dense sampling remains available in replay comparisons. Debug cycle timing identifies `sampling=even_grid`.

September 23 local regression: 15 retained full frames, seven conditions (original, digital brightness plus/minus 15 percent, small translations and plus/minus one degree rotation), both sampling modes: all 210 frame evaluations passed alignment and all six visibility checks. Maximum circular difference between dense and sparse predictions across these conditions: 0.010893 on the 0-10 dial scale. These are synthetic variants of existing images, not independent labels or physical lighting tests.

Earlier test-board replay with this three-marker sparse algorithm took a median 14.36 seconds across 15 saved frames and matched frozen reference tensors and scores exactly. That replay does not measure the full camera, publication or archive cycle. The new normal-path call still requires device verification; sustained 30-second valid capture cadence remains unproven.
