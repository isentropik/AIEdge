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
