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

## Test-board profile — September 23

Installed build: 2026-09-23 21:13:31 UTC, test board aiedge-744b20.
Three saved-JPEG runs matched all six expected feature/output vectors. Median
whole diagnostic time was 27.857 seconds at unchanged 160 MHz. Median per-step
totals across all six dials were:

| Step | Seconds |
| --- | ---: |
| Affine bicubic crop warp | 17.394 |
| Grayscale and contrast | 0.093 |
| Visibility | 1.130 |
| Blur | 0.401 |
| Polar coordinate construction | 1.043 |
| Feature sampling and quantization | 1.187 |

The warp is the dominant target. These timings include diagnostic timer overhead;
medians of individual steps need not sum to the median whole run. No live camera
capture, publication or archive upload was measured. Configuration stayed
byte-identical, no camera cycles ran, and temporary transfer access was removed.
Private evidence: `aiedge-profile-candidate/repeated-jpeg/preprocessing-summary.json`
and recorded installation `recorded-20260923T211738Z` in local firmware-port tests.
