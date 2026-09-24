# Meter setup status

The setup flow now starts with meter type and units. The same page is available in Settings. It supports the backend's gas, water and electricity unit choices, separates US and imperial gallons, and asks for the printed register multiplier and optional secondary-wheel quantity per complete revolution. No model-generated suggestion is presented as a confirmed meter type.

Compatible gas profiles now activate display-unit conversion for current consumption diagnostics and the additional `display` object in accounting HTTP/MQTT snapshots. Activation is immediate after a durable save and restored at startup. Canonical ft³ quantities, retained history, legacy readings and Home Assistant entity units are unchanged. Generic model activation, meter-specific geometry and history migration remain incomplete. The installed frozen gas model is not a water/electricity recognition model.

The form requires explicit confirmation of the printed scale, uses a revision token, rejects invalid or missing units/scales, and disables saving until reloaded after a save attempt. A saved physical scale is locked, matching backend history protection. It does not retry uncertain writes or restart the device. Unsupported types/scales remain saved but inactive with `calibration_required`; a compatible profile reports `display_only`. Saving a display preference does not change the recognition model or physical scale.

Validation: Node form tests cover supported units, incompatible dimensions, invalid/nonfinite scales, missing confirmation, loading, saving, stale revisions, locked scales and no implicit retries. Browser checks covered the 390px mobile layout in light/dark themes, unit options, wheel fields, the confirmation checkbox and the setup iframe. Installed on the test board and verified as described below.

## Verified test-board result

Bundle `c00a03a9475a36925ebcb9fef548949bc2e0b9b024bcadc402523352ad3f120d` passed managed OTA and verified boot. All four new/updated page assets matched their packaged source bytes. The established gas profile (ft³, register multiplier 1, secondary wheel 5 ft³ per revolution) was saved through the authenticated endpoint and read back exactly. A further restart preserved the profile and original active configuration. Website credentials were preserved.

Private evidence is under `needle-training/firmware-port-tests/aiedge-meter-setup-ui`: `ota/result.json`, `profile-save/result.json` and `profile-save/restart.json`. The pre-save snapshot records that no profile existed. No production device was changed. Saving/retaining the profile does not establish activation, generic-meter support, or reading accuracy.

## Display conversion verification

The C++ serializer tests verify ft³-to-m³ conversion, unchanged canonical quantities, compatible-calibration checks, null unavailable/rejected/ambiguous point estimates, and stale cumulative bounds without a stale estimate. HTTP handler tests verify successful activation after a durable save and rejection of stale edits. Node tests cover active-save messaging and unknown/stale consumption display. The ESP32 build passed. Bundle `ed791cd6a6064c5f3c9210ca094ae31431144f03e4004747b754a72b153da4f0` is installed and verified on the test board. Its saved gas profile activated display conversion at startup. A live ft3 to m3 to ft3 trial applied immediately without restarting, preserved all canonical accounting fields and configuration, and kept missing readings null. The original profile was restored. All six UI assets matched source bytes. This hardware trial had an empty reading session; numerical conversions were tested with host fixtures. MQTT broker delivery has not been tested. Evidence: `aiedge-display-units/ota`, `display-trial/result.json` and `assets-verified.json` under the private firmware-port-tests directory.

The follow-up bundle `e277163864b3093865c5ad2f8bffd40abceb9756e5a3fbe0bbe75370f18522a4` corrects the diagnostics unit-label encoding. OTA/boot, exact readback of all six UI assets, strict UTF-8 decoding, and the restored active ft3 preference passed. UTF-8 validation is now included in the form tests. Evidence: `aiedge-display-units-utf8/final-verification.json`.


## Saved-history display conversion — September 24

The local history API now adds a `display` view of completed-segment consumption in the active ft3/m3 preference. Existing `covered_minimum_ft3` and `covered_maximum_ft3` fields and stored records are unchanged. The history UI uses this view, retains the active-segment/gap exclusions, and shows Unknown for invalid bounds. An unavailable/incompatible preference leaves canonical quantities explicitly labeled as stored units.

The actual HTTP-handler regression (`python tools/bundle-tests/test_history_display.py`, using a Python environment with ziglang), current diagnostics UI tests, and ESP32 build pass. Fixtures cover numerical conversion, unchanged canonical fields, invalid/reversed/nonfinite bounds, inactive profiles and scan state. Bundle `47d72cb445c39b72c061331b5c2f75b17d727e24ea3e66e9dbb34e31fa519e45` is installed on the test board with verified boot and preserved configuration/profile/password. The profile-switch test stopped before any write: the camera is unavailable, the flow task does not start, and the compatible saved profile reports `pending`. Display preference restoration currently lives inside flow initialization. Camera-independent profile startup must be fixed before this hardware unit-switch check can pass. Numerical conversion remains host-verified only.

The camera-independent startup correction is now installed in bundle `9d0fdc7a4d249ed72f97f944dbd1e05cf8b93d1acabaeaae537e80b399750f37`: shared journal recovery restores compatible display preferences before HTTP routes start, guarded by SD/bundle readiness. Flow reload uses the same helper. Host fixtures cover missing/incompatible profiles, untrusted storage, read failure, malformed and interrupted journals, pending cleanup and unchanged file bytes. Verified boot preserved configuration, profile and password. With `camera_available=false`, the profile reported `display_only` before any settings write. The ft3-to-m3-to-ft3 history trial passed with original preference restored, unchanged canonical accounting/history fields, no restart and no camera cycles. Existing history was empty (zero segments), so unavailable bounds stayed null; nonzero numerical conversion is covered by host fixtures. The served diagnostics script and build metadata matched the package. Evidence: `aiedge-profile-startup-01/ota`, `history-unit-trial/result.json` and `served-assets.json` in the private firmware-port-tests directory.


## Alignment placement feedback — deployed to the test board September 24

The local two-marker editor now checks the real crop dimensions for overlap and image boundaries, and reports center separation as a fraction of the reference-image diagonal. The 25% spacing suggestion is explicitly a placement guideline, not a validated matching threshold. Feedback follows the selected draft rectangle without saving or moving marker positions. It uses saved reference crops only; it does not capture a camera image or change device settings.

Node geometry and editor-state tests pass for scale invariance, overlap, boundaries, missing/invalid coordinates, reverse drag, saved crop sizes and unchanged marker positions. Browser review passed for the 390px embedded editor and standalone light/dark themes, including live numeric boundary feedback. Guidance padding and enabled-button contrast were corrected. Bundle `833ff837e10db98cdceca8013b3995de7cd05da7918e67fd9708c15e87fd185d` passed 79 host scripts, seven UI scripts, a clean ESP32 build, managed OTA and verified boot. Configuration, profile/revision and password protection were preserved. Four served assets matched the package byte-for-byte. Evidence: `aiedge-marker-spacing-01/browser-review.json`, `ota/result.json` and `served-assets.json` under the private firmware-port-tests directory. Production and the public installer were unchanged. Automatic feature selection and a third independently validated marker remain separate unfinished work.


## Offline automatic-marker consistency review — September 24

The local proposal tool now checks each candidate against every already-aligned selection frame, rather than relying only on median-image uniqueness. Provisional gates require correlation at least 0.8, a competing-match margin at least 0.15, and drift no greater than 3 pixels. Moving dial rectangles remain excluded. These are development gates, not calibrated confidence or proof that a marking is fixed.

Eight host tests cover stable gain/brightness changes, a duplicate appearing in one frame, a displaced or missing feature, invalid batches and previous blank/excluded/glare cases. On the existing 15-frame selection set, the tool retained 16 candidates and selected three. Reused development stress fixtures produced 360 accepted normal-condition marker checks with maximum residual 2.358 pixels; all 45 severe 10-degree rotation checks were rejected. Identity cases appear in both fixture suites, so these counts are not independent captures or new accuracy evidence.

No device marker, model, training label or firmware was changed. Independent captures and on-device integration remain pending. Private evidence: `automatic-markers-multiframe-20260924/verification-summary.json` and `automatic-markers-multiframe-stress-20260924/results.json` under firmware-port-tests.


The proposal now freezes the exact median reference array with a hash and records selection-image hashes. A later saved capture outside that 15-image set passed all three marker checks, with correlations 0.9891–0.9910 and zero integer-pixel drift after existing two-marker registration. The weakest competing-match margin was 0.1572, close to the provisional 0.15 gate. This is one additional capture, not population accuracy evidence; hash separation does not exclude visually similar frames. Four rejection tests cover selection overlap, damaged template data, capture-hash mismatch and changed imaging settings. No thresholds or templates were changed after seeing the later capture.

Evidence: `automatic-markers-frozen-20260924/suggestions.json` and `automatic-markers-excluded-capture-20260924/result.json` under private firmware-port-tests. Existing model/training splits and device settings are untouched. Replacing the active alignment pipeline and on-device validation remain pending.


## Firmware competing-match rejection — deployed on the test board September 24

The portable matcher now rejects a second separated peak within 0.05 correlation of the best local-search match, excluding an eight-pixel neighborhood around that peak. `Ambiguous` is appended to the status enum so previous numeric status values remain unchanged. Failure preserves the caller's output. This provisional local-search margin is distinct from the offline whole-image proposal gate and is not an accuracy probability.

The exact/near-duplicate C++ fixture rejects both ambiguous cases while accepting a unique marker. All 16 retained real frames preserve their original transforms within floating-point tolerance. The actual three-marker pipeline retains expected outcomes on 195 existing stress cases (120 accepted, 75 rejected). Bundle `31a3388e5eab85f826581187feae4b476a9726506cc17149f69dcfaa3c641339` passed 80 host scripts, seven UI checks and a clean ESP32 build. Managed OTA and verified boot preserved configuration/profile/password. One sparse saved-JPEG six-dial test produced exact tensor/output parity in 13.946137 seconds with zero camera cycles and unchanged configuration. Both served build metadata assets matched the package. This is saved-fixture compatibility, not live capture cadence, broad ambiguity rejection on hardware, or new reading accuracy. Evidence: `aiedge-alignment-ambiguity-01/ota`, `saved-image-check` and `served-assets.json` under private firmware-port-tests. Production and the public installer are unchanged.


The subsequent [full saved-image replay](REPLAY-VALIDATION.md) passed on all 15 frames and 90 dial outputs, with a 14.001-second median processing time and zero status-request errors. It remains a diagnostic compatibility benchmark, not a live capture or independent accuracy result.


## Proposal overlay reference correction — September 24

The offline marker review now embeds the exact frozen aligned median used for
selection, rounded to 8-bit grayscale only for display. Previously the SVG used
a separate cached JPEG, so the background was not guaranteed to share the
proposal geometry. Ten local tests pass, including decoding the embedded PNG,
checking its pixels and dimensions, and verifying the input array is unchanged.
The existing frozen proposal was rendered again after verifying its reference
hash; no marker, calibration, model or device setting changed. Evidence:
`automatic-markers-reference-review-20260924/verification.json` under the private
firmware-port-tests directory. This corrects visual review provenance; it does
not add recognition accuracy evidence or activate automatic setup.


## Later retained frame and human review — September 24

A subsequent cached full image, retrieved at 19:03:13 UTC, passed the active
alignment and all six visibility checks in the actual firmware host pipeline
with both dense and sparse sampling. Its capture timestamp is unknown. The user
accepted the displayed fourth-main, last-main and secondary estimates of 5.34,
4.78 and 7.15 on the 0–10 scale. This is approximate visual confirmation of
model-assisted displays, not independent hundredth-unit ground truth or three
independent captures. The image and review derivatives remain held out.

The confirmed main pair still has a 0.138 circular residual: the following
4.78 implies 5.478, versus the preceding 5.34. This exceeds the provisional
0.11 combined bound. Both host diagnostic and firmware accounting use that
consistency rule; with valid timestamps, accounting rejects inconsistent main
inputs as Review/MainInconsistent. This cached image has no capture timestamp
and establishes no consumption or flow. The cause remains unresolved; no
calibration, tolerance, raw reading or model was changed to force agreement.

The same image rejected one marker in the separate frozen automatic-placement
proposal: its competing-match margin was 0.13785 against the provisional 0.15
gate, despite a 0.97399 best correlation and zero integer-pixel drift. The other
two proposed markers passed. This is a proposal failure, not an active-alignment
failure. Templates and gates remain frozen; the proposal is not ready to activate.

Private evidence: `current-frame-firmware-check-20260924/result.json`,
`current-frame-review-20260924/confirmation-evaluation.json`,
`current-frame-review-20260924/consistency-investigation.json`, and
`automatic-markers-current-frame-20260924/result.json` under firmware-port-tests.


## Cross-dial rejection detail — deployed to the test board September 24

The diagnostics page now explains a main-dial inconsistency using the current
raw observation and reported error assumption. It names each disagreeing pair
from highest to lowest place value and shows measured position, linked position,
circular residual and allowed bound on the 0–10 scale. The warning remains visible
without a compatible display-unit preference. No raw reading, threshold or
accounting state is changed. Other rejection reasons are also displayed.

Node tests pass for the confirmed-frame discrepancy, circular rollover, invalid
inputs, missing preferences, immutable observations and existing unknown/stale
quantity handling. Bundle `4b32be5d916be370211fb3a6d82cba5452819156772223764bbd25afe22dc4e9`
passed the full packaging checks and clean ESP32 build, managed OTA and verified
boot. Configuration, profile and password were preserved. Both served diagnostics
assets matched package bytes, with zero camera attempts and archival inactive.
The older local refresh fixture was corrected to include the accounting panel
and verify all four GET requests. Rendered visual review remains pending; no
recognition accuracy or live-capture claim is made. Evidence: private
`aiedge-dial-diagnostics-01/ota/result.json` and `served-assets.json`.


The public UI regression now derives panel IDs from the actual diagnostics HTML
and exercises all four refresh requests. It checks rejected-frame explanations,
unknown interval/flow/stale cumulative estimates, literal-text rendering of
device reasons, and clearing the previous observation when accounting refresh
fails. These checks pass. Browser navigation to the deployed page was blocked
by the browser access policy, so rendered visual verification remains pending.
This follow-up changes tests and documentation only; no firmware redeployment
is required for it.
