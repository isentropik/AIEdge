# Saved-image robustness check

This local check uses one protected production-meter cached image, the frozen
model, and the current C++ sparse preprocessing and decoder. It makes no device
changes and does not retrain. The unmodified replay first had to reproduce the
previous sparse readings within 0.000001. Source, model, executable and image
hashes are recorded in [the results](IMAGE-PERTURBATION-RESULTS.json).

| Modification | Observed outcome |
| --- | --- |
| RGB brightness multiplied by 0.8, 0.9, 1.1 or 1.2 | All six accepted; largest circular change below 0.012 on the 0–10 dial scale |
| RGB brightness multiplied by 1.5, clipped at 255 | All six accepted; largest change 0.0251 |
| RGB brightness multiplied by 0.5 | Alignment passed; last main and secondary failed visibility, rejecting the frame |
| Shifts of 2 pixels in each cardinal direction, diagonal shifts of ±5 pixels, and 12 pixels right | All six readings unchanged after registration |
| Shift 30 pixels right | Alignment rejected |
| Rotations of ±1 degree around image center | All six accepted; largest change 0.0241 |
| Rotations of ±3 degrees | Alignment rejected |

There are 19 cases including the baseline, derived from **one** image. These are
stability and rejection checks, not 19 new accuracy observations. Brightness
multiplication does not reproduce changed glare, LED spectra, exposure noise or
shadows. Rotation uses bilinear interpolation and translation introduces black
borders. Results do not define universal operating limits or prove ESP32 timing.
The original small adjacent-dial consistency warning remains unresolved; stable
predictions do not make that warning disappear.

All derivatives remain training-ineligible, linked to their held-out parent hash.
No new human labels were inferred. The two human numeric labels on the source
image remain 5.3 and 4.5; the secondary reading remains unconfirmed.

The separate receiver surrogate suite also passed all 41 tests, including its
generated HTTPS launcher, duplicate delivery, authentication and interruption
checks. That suite uses disposable loopback receivers; it does not demonstrate
simultaneous ESP32 inference and TLS memory capacity.


## Local bright-patch failure and publication guard (September 24)

A subsequent protected frame was tested with two horizontal brightness gradients
and twelve synthetic Gaussian white overlays, plus its unchanged baseline (15
cases). This used the same frozen model and C++ sparse preprocessing. No live
lighting was changed, no labels were inferred, and no evaluation images were
used for training.

A strong overlay centered on the second main dial passed marker alignment and
visibility checks but changed its estimate from **2.50648 to 7.92255** (shortest
circular difference **4.58394** on the 0–10 scale). This disproves any claim that
passing the visibility check alone guarantees a usable reading. The overlay is
a synthetic stress case, not a measured reproduction of physical glare.

Inspection found a separate publication bug: accounting rejected contradictory
main dials, but the analog stage still marked every ROI accepted and returned
success. The stage now returns failure when accounting rejects the observation.
All six normal ROI results remain unavailable; the accounting status retains the
raw estimates and original reason, without counting the rejection twice. The
existing controller then stops before normal postprocessing and publication.
Ambiguous whole-turn counts remain valid observations and are not rejected merely
because consumption cannot be uniquely determined.

The actual analog-source host harness checks the recorded bright-patch estimates,
inconsistent sequences, missing capture timestamps, backward totals, preserved
raw observations and rejection counts, and accepted ambiguous intervals. It
compares 40 preprocessing tensors against six frozen references; inference and
device services are stubbed. The separate controller harness checks stopping
publication on recognition failure. These are behavioral regression tests, not
additional recognition-accuracy evidence.

The model, calibration and tolerances have **not** changed. In particular, the
unmodified recent frame has an adjacent-dial residual of about **0.1245**, above
the existing combined **0.11** allowance. It also fails this consistency rule.
The publication guard prevents accepted contradictory readings; it does not fix
the underlying recognition/calibration mismatch or establish glare robustness.

Local evidence: `local-lighting-stress-20260925/result.json`,
`aiedge-accounting-gate-01/validation` in the candidate ZIP, and its recorded
installation results. Parent-image SHA-256:
`5f98f87f4ebf74acfd418ad34f21fd726f9cfaa5e1bf6dd6e455b9807dfc4fbc`.
