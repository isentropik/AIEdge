# Meter setup status

The setup flow now starts with meter type and units. The same page is available in Settings. It supports the backend's gas, water and electricity unit choices, separates US and imperial gallons, and asks for the printed register multiplier and optional secondary-wheel quantity per complete revolution. No model-generated suggestion is presented as a confirmed meter type.

This is explicitly a setup preview: profiles can be saved, but active calibration, existing readings, totals and publication units are unchanged. Generic model activation, meter-specific geometry and history migration remain incomplete. The installed frozen gas model is not a water/electricity recognition model.

The form requires explicit confirmation of the printed scale, uses a revision token, rejects invalid or missing units/scales, and disables saving until reloaded after a save attempt. A saved physical scale is locked, matching backend history protection. It does not retry uncertain writes or restart the device. Display-unit preferences are saved metadata until activation is implemented.

Validation: Node form tests cover supported units, incompatible dimensions, invalid/nonfinite scales, missing confirmation, loading, saving, stale revisions, locked scales and no implicit retries. Browser checks covered the 390px mobile layout in light/dark themes, unit options, wheel fields, the confirmation checkbox and the setup iframe. Device deployment is pending.
