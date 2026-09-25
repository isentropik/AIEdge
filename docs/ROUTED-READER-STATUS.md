# Two-model reader: verified on the test board

The five main dials now use the linked-target candidate. The secondary wheel keeps
the original model. The test-board update passed boot, configuration, profile and
password checks. The production meter has not been modified.

Current test bundle:
`516a2c5807a66807e9a14c3db964b1b02bd7b65e808564f409eb7b81013d2876`.
Package SHA256:
`bce0b4bc5a97930b29aa0333fbdaa4d804107c2cf3f9ad67c4e6efe6e3eb1da6`.
Previous bundle retained for rollback:
`2be8e759f4275bfe7fe9ca9507111166655f5adadd2263035ad3f137e1bbd685`.

| Check | Result |
| --- | --- |
| Clean build | 90 host scripts and 9 UI scripts passed |
| Raw-vector hardware inference | All six output tensors matched exactly |
| Full RGB frame | All features and outputs matched; 19.356447 seconds |
| Fifteen JPEG replays, 30-second start slots | All features and outputs matched |
| JPEG time | 11.57-11.90 seconds; median 11.75 seconds |
| Missed replay slots / restarts | Zero / zero |
| Camera captures | Zero |

Saved-image tests bypass camera capture and normal publication. They demonstrate
on-board preprocessing, model switching and reference-runtime parity, not live
capture cadence or independent reading accuracy. Free heap was 2,015,219 bytes
before the replay series and 2,015,227 afterward; these two observations are not
a general memory-leak proof. Camera initialization still reports error 0x105.

## Model and update integrity

| Role | SHA256 |
| --- | --- |
| Main | `9c145e67e9008bf1e17567cd69baa48ce54af3b1d6b7fa0e1aeeb6b5ce9ec6a5` |
| Secondary | `b039dd72fa6cb2c821f9de2154a44879d5ce9620c862a2129176e2e18db05ed0` |

Both models are 12,720 bytes. The complete reader identity is
`deb371204699a147e4fed745dc06cb1acbd45b2abf01353a4b81cdc1bd5858d4`.
Accounting, history and archived image metadata use this identity. Incompatible
older checkpoints are rejected and retained; they are not erased or reinterpreted.
A retained incompatible checkpoint prevents accounting activation until resolved.

Boot requires both compiled model identities before exposing bundle assets. Each
load checks the exact bytes again before interpreting them. Model switching uses
one interpreter owner; its borrowed workspace retains a fixed boundary. A failed
late switch leaves all six readings rejected. Calibration and tolerances did not
change. The v2 primary model identity remains compatible with earlier installers,
while required extra assets are enforced by the new application's boot contract.

The role loader's host regression uses actual file I/O, SHA256 and allocator code
with a stub interpreter. It covers six switches, nine rejected loads, workspace
preservation, missing/swapped assets and allocation/tensor-contract failures:

```
python tools/bundle-tests/test_model_roles.py --idf PATH_TO_ESP_IDF --main-model PATH_TO_MAIN_MODEL --secondary-model PATH_TO_SECONDARY_MODEL
```

The full suite also caught a receiver concurrency failure on Windows. Short
publication and readback operations are now serialized within the receiver
process. All 106 public receiver tests pass. Cross-process and genuine storage
errors still propagate without acknowledgement or blind retry.

## Remaining validation

The selected combination passed 27 reused reviewed crops; these informed model
selection and do not establish independent accuracy. One fresh protected cached
frame passed alignment, visibility and main-dial consistency in both dense and
sparse preprocessing, but remains unlabeled and excluded from training. Thirty-two
parity fixture files contain 192 dial vectors, including repeated dense/sparse
inputs; they are not 192 independent examples.

Fresh labeled coverage, live capture and publication timing, physical LED checks,
and end-to-end remote-storage validation remain separate requirements. Test-board
replays do not establish those outcomes.

Local evidence is under
`needle-training/firmware-port-tests/aiedge-routed-reader-02/`: build/source hashes,
packaged tests, OTA backup/readback, `role-diagnostics/`, `replay-30s/` and
`verified-summary.json`. The earlier failed build is preserved in
`aiedge-routed-reader-01/`. The fresh protected image was retrieved at
2026-09-25T02:59:44Z; retrieval time is not its capture time.
