# Reviewed-image port check

September 23, 2026: the existing 27 protected, human-reviewed crop images were
evaluated through the firmware's scalar stb JPEG decoder, RGB-to-grayscale
conversion, contrast/visibility checks, radius-0.4 blur, quantized polar features
and reading decoder. The frozen int8 model used TensorFlow Lite 2.16.1 desktop
reference kernels. No training or label changes were made.

| Dial | Reviewed crops | Passed within 0.1 | Rejected |
| --- | ---: | ---: | ---: |
| Secondary, 5 cubic feet per revolution | 22 | 22 | 0 |
| Highest-order main | 1 | 1 | 0 |
| Second main | 1 | 1 | 0 |
| Third main | 1 | 1 | 0 |
| Fourth main | 1 | 1 | 0 |
| Last main | 1 | 1 | 0 |
| Total | 27 | 27 | 0 |

Error is circular distance on each dial's 0–10 scale. Maximum error was
0.09338973. Rejections counted as failures. Exact image hashes were checked;
there were no duplicate evaluation hashes or exact training-image overlaps.
Earlier training-pose similarity flags still apply: absence of an exact hash
overlap does not establish statistical independence.

This reuses the existing validation set; it is not 27 new accuracy samples.
Some labels were confirmations of displayed predictions. Main-dial operating
coverage is narrow, and this result provides no guarantee for unseen positions,
different lighting or changed geometry.

The original frozen crop calibration was used, preserving the fixed needle pivot.
Full-frame marker registration, transported calibration and the normal controller
were not invoked. The coordinate loop mirrors `prepareDial`; it is not a direct
full-pipeline test. Firmware primitives ran on the host. This batch was not run
on the ESP32, and the separate six-vector ESP32 check does not fill that gap.

Frozen model SHA-256:
`b039dd72fa6cb2c821f9de2154a44879d5ce9620c862a2129176e2e18db05ed0`.
Original crop-calibration SHA-256:
`569ae56ff64edc5d9ed56a00fe701d6c7cf246159f73dcca64c0827694ac4468`.

Private evidence: `needle-training/firmware-port-tests/reviewed-crop-port-audit-02/result.json`
in the development workspace. It records per-image results, label provenance,
source-header hashes and decoder hash. The earlier audit folder preserves a failed
compile caused by the publication checkout lacking its stb submodule; the successful
run used the build checkout's actual dependency. Private images remain unpublished
and excluded from training.

## Faster sampling checked against the same labels

A follow-up host check uses the current firmware `warpCrop` implementation with
an identity transform on each original reviewed JPEG crop, in both dense and
even-grid modes. Both pass **27/27**, with no rejected crops. Maximum error is
**0.09338973** for dense sampling and **0.09003447** for even-grid sampling.
The dense control reproduces all prior predictions exactly and checks that
identity resampling preserves every decoded RGB byte.

The largest dense/even-grid reading difference is **0.01279187** on the 0-10 scale.
This is a regression check, not evidence that even-grid sampling improves accuracy.
The model, labels, split protection and original crop calibration remain unchanged.

This test resamples already JPEG-compressed crops; normal firmware samples the
original full image after marker registration. It therefore does not close the
full-image human-label validation gap or establish ESP32 end-to-end accuracy.
The cached full-image trial records retrieval times and unknown capture times;
its images must not inherit labels from nearby archived crops.

Private evidence: `reviewed-crop-sparse-audit-01/result.json` and
`reviewed-crop-dense-control-01/result.json` under the existing firmware-port-tests
directory. Both record source hashes, per-image results and unchanged label provenance.
