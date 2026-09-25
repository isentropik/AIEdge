# Two-model reader integration

Status: local integration in progress. The test board still runs the original
frozen model under bundle
`2be8e759f4275bfe7fe9ca9507111166655f5adadd2263035ad3f137e1bbd685`.
No production configuration or models were changed.

The candidate assigns five main dials to the linked-target model and keeps the
original model for the secondary wheel. The compiled contract is generated from
actual model artifacts in `PolarModelRoles.h` and `PolarModelRoles.json`:

| Role | SHA256 |
| --- | --- |
| Main | `9c145e67e9008bf1e17567cd69baa48ce54af3b1d6b7fa0e1aeeb6b5ce9ec6a5` |
| Secondary | `b039dd72fa6cb2c821f9de2154a44879d5ce9620c862a2129176e2e18db05ed0` |

Both files contain 12,720 bytes. The complete routing identity is
`deb371204699a147e4fed745dc06cb1acbd45b2abf01353a4b81cdc1bd5858d4`.
It is not yet the active accounting identity.

## Implemented and checked locally

- Role loading hashes the exact bytes before interpreting the model. It rejects
  incorrect roles, corruption, missing files, invalid lengths and invalid enums.
- Once borrowed, the workspace boundary remains fixed. A later read cannot
  overwrite the workspace, and a smaller model cannot move its address.
- Actual-method tests with real SHA256 and file I/O pass six model switches and
  nine rejected loads, preserving the workspace. The interpreter is stubbed;
  this does not prove hardware switching or tensor-arena allocation behavior.
- Bundle selection accepts application-supplied required asset identities and
  checks them before exposing any asset. Required roles cannot use legacy
  fallback, even in optional mode. Old callers retain their existing contract.
- Existing v2 staging verifies an extra main-model asset. The old primary hash
  remains unchanged. The required-role checks pass valid selection and seven
  rejection cases alongside the existing bundle and transaction regressions.
- 32 diagnostic vector files (192 dial vectors, including repeated dense/sparse
  inputs) were regenerated locally. Every original output matched reference
  inference first; input tensors and secondary outputs remain byte-identical.
  These are parity fixtures, not new labels, training data, or independent poses.

Reproduce the loader check with Python, ziglang, ESP-IDF sources and the two
model artifacts:

```
python tools/bundle-tests/test_model_roles.py --idf PATH_TO_ESP_IDF --main-model PATH_TO_MAIN_MODEL --secondary-model PATH_TO_SECONDARY_MODEL
```

The role APIs also compile successfully in the ESP32 managed build. This was
an incremental compile check, not a packaged clean release or deployment.

## Still required before activation

Connect boot selection to both compiled role requirements; update production
recognition, initialization and every diagnostic to switch roles consistently;
regenerate diagnostic catalog hashes; package both models; and apply the new
complete reader identity to accounting, history and image metadata. Verify that
old checkpoints are rejected without being silently reinterpreted or erased.
Then run the full clean build, test-board OTA, exact replay comparisons and
model-switch timing/memory tests. Do not infer this work is deployed from the
presence of the role API or generated contract.

The selected combination passed 27 reused reviewed crops; that influenced model
selection and does not establish independent real-world accuracy. Fresh validation
and live-camera evidence remain required.
