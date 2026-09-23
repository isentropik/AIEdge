# PolarV1 development configuration

Local development only. Not a deployment proposal or an approved live change.

The default upstream analog/digital paths remain available. The new path is
explicitly selected inside `[Analog]`:

The configuration-page source template now has an optional **Use frozen polar
reader** checkbox. Unchecked keeps the Reader line disabled and preserves the
stock path; checked writes `Reader = PolarV1`. The shared parser/writer knows
this setting and passes absent/enabled/commented round-trip checks. This does
not automatically choose the model or change geometry. The generated page now
contains this control and the RGBW white-channel control. Generation uses pinned
Markdown 3.7 and resolves paths relative to the generator; two runs from different
working directories produced identical files. Browser verification and release
packaging remain required before deployment.

```ini
[Analog]
Reader = PolarV1
Model = /config/polar-int8.tflite
main.10000k 76 245 144 146 true
main.1000k 57 106 144 146 false
main.100k 189 66 144 146 true
main.10k 327 65 145 146 false
main.1k 461 108 143 145 true
secondary.5 257 277 147 148 false
```

The model must be exactly 12,720 bytes, SHA-256
`b039dd72fa6cb2c821f9de2154a44879d5ce9620c862a2129176e2e18db05ed0`.
The loaded bytes are hashed before model interpretation, on initialization and
each cycle. Tensor dimensions, signed-int8 type and quantization are also checked.
There is no fallback to a different model. The bundle is in the parent workspace
at `needle-training/polar-prospective-v1/reader-bundle`.

This version is bound to the existing six-region geometry, names, order and
directions. It requires 640 x 480 RGB input, initial rotation 0.3 degrees, no
initial flip or rotation antialiasing, two reference markers, and upstream
alignment set to `off`. It performs its own fixed-template marker registration
and uses the compiled frozen perspective transforms and distinct needle pivots.
Changing physical camera alignment, ROIs or markers requires renewed calibration
and validation; this does not adapt geometry automatically.

No RGB thumbnail or float-tensor path is used for polar inference. RGB thumbnails
are previews only. Scratch space uses the unused tail of the existing reserved
model region, after the small verified model, and never overlaps the tensor arena.
All six readings are committed only after all pass. Geometry, alignment,
visibility, allocation and invocation failures invalidate the frame and stop
normal downstream reading publication with `Recognition failed` status. Previously
retained MQTT readings are not cleared by this status; freshness/error publication
still needs integration. This guard is not a universal glare/obstruction detector.

## Required before a live trial

- Verify ESP32 TFLite Micro runtime output against golden feature fixtures and
  measure arena/PSRAM high-water usage. Build success is insufficient.
- Compare the direct device RGB image path against validation performed on
  downloaded JPEGs; quantify compression/decoding effects on alignment and readings.
- Complete calibrated raw-position, cross-dial diagnostics, cumulative volume,
  timestamped secondary consumption, ambiguous-turn and restart handling. Existing
  upstream postprocessing alone is not the requested secondary accounting system.
- Preserve current ROI logging and preview behavior, complete explicit failure
  reasons/freshness in HTTP/MQTT/HA, and verify manual-stage endpoints.
- Expose/save the Reader option in the configuration UI without losing it on edits.
- Validate camera/stream/recognition ownership and bounded interactive behavior.
  Per-dial yielding does not itself prove web responsiveness.
- Add full capture-to-publication timing, capture timestamps and sustained cadence
  evidence. Current DEBUG timing covers marker registration and per-dial local
  preprocessing/inference only; no 30-second performance claim is established.
- Finish lighting/configuration requirements in the parent firmware backlog,
  prepare exact flash/recovery artifacts, and obtain approval for the live trial.

Host regression images remain excluded from training and provide no new labels.
