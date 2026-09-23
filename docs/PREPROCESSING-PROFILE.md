# Preprocessing diagnostic timings

The explicitly requested saved-JPEG diagnostic reports six per-dial durations in
`preprocessing_profile`: warp, grayscale/contrast, visibility, blur, coordinate
construction, and feature sampling/quantization. Values use the device monotonic
clock and include timer overhead. `attempted_mask` identifies the measured steps;
a zero duration with an unset bit means unmeasured, not a free operation.
An early failure retains elapsed time for the attempted operation. The normal
recognition path does not request these timers or make additional clock calls.

The frozen model, calibration and arithmetic are unchanged. Thirty saved
full-frame/decoder paths (180 dial results) preserved exact acceptance, visibility
scores and input features. Actual JPEG diagnostic, normal flow/accounting and
HTTP serialization checks passed on the host with the documented platform and
inference substitutes. These are not device timing results or new accuracy data.
The profile must be measured on the test board before selecting an optimization.
