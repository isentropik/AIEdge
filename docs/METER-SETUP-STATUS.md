# Meter setup status

The setup flow now starts with meter type and units. The same page is available in Settings. It supports the backend's gas, water and electricity unit choices, separates US and imperial gallons, and asks for the printed register multiplier and optional secondary-wheel quantity per complete revolution. No model-generated suggestion is presented as a confirmed meter type.

This is explicitly a setup preview: profiles can be saved, but active calibration, existing readings, totals and publication units are unchanged. Generic model activation, meter-specific geometry and history migration remain incomplete. The installed frozen gas model is not a water/electricity recognition model.

The form requires explicit confirmation of the printed scale, uses a revision token, rejects invalid or missing units/scales, and disables saving until reloaded after a save attempt. A saved physical scale is locked, matching backend history protection. It does not retry uncertain writes or restart the device. Display-unit preferences are saved metadata until activation is implemented.

Validation: Node form tests cover supported units, incompatible dimensions, invalid/nonfinite scales, missing confirmation, loading, saving, stale revisions, locked scales and no implicit retries. Browser checks covered the 390px mobile layout in light/dark themes, unit options, wheel fields, the confirmation checkbox and the setup iframe. Installed on the test board and verified as described below.

## Verified test-board result

Bundle `c00a03a9475a36925ebcb9fef548949bc2e0b9b024bcadc402523352ad3f120d` passed managed OTA and verified boot. All four new/updated page assets matched their packaged source bytes. The established gas profile (ft³, register multiplier 1, secondary wheel 5 ft³ per revolution) was saved through the authenticated endpoint and read back exactly. A further restart preserved the profile and original active configuration. Website credentials were preserved.

Private evidence is under `needle-training/firmware-port-tests/aiedge-meter-setup-ui`: `ota/result.json`, `profile-save/result.json` and `profile-save/restart.json`. The pre-save snapshot records that no profile existed. No production device was changed. Saving/retaining the profile does not establish activation, generic-meter support, or reading accuracy.
