# Test-board processing measurements

September 23, 2026. Firmware application SHA-256 `191b738f6a1e2a60f7bce6fbe99cc42855eedbb89a24975c82ae68d25114a1ce`.

Three repeated full-RGB diagnostic runs were performed at each supported CPU setting. Startup logs confirmed the active frequency. Every run registered the fixed held-out image, prepared all six dial inputs and matched all feature and model-output bytes against the frozen reference.

| CPU setting | Runs | Minimum | Median | Maximum |
| --- | ---: | ---: | ---: | ---: |
| 160 MHz | 3 | 26.942 s | 26.943 s | 27.039 s |
| 240 MHz | 3 | 18.227 s | 18.245 s | 18.297 s |

The 240 MHz setting reduced median processing time by 32.3%. The model, calibration, firmware, input image and comparison tolerances were unchanged. Repeated use of one image tests implementation consistency; it adds no independent accuracy evidence.

Three separate no-flash camera requests at each setting returned JPEGs that decoded to 640 by 480 pixels. Camera-request measurements include HTTP transfer and are not sensor exposure timestamps. They are not added to the diagnostic duration to claim a complete recognition cycle. These captures remain unlabeled and excluded from training.

The processor temperature reported at the end of the short runs was 69 C at 160 MHz and 71 C at 240 MHz. These readings do not establish sustained thermal behavior. Free heap at those observations was 1,001,503 and 1,001,491 bytes, respectively; they are not peak-memory measurements.

The original configuration was restored byte-for-byte, including 160 MHz and the original logging level, then a new boot was verified. No production meter or Home Assistant settings changed. No private camera images are included in this repository.

## What remains

This diagnostic excludes camera acquisition, JPEG decoding, normal preview/accounting/publication stages and archive upload contention. A sustained normal-cycle trial must measure these together, with accepted readings, missed schedule slots, latency and memory margins. The 30-second end-to-end target is not yet verified. The public firmware default remains unchanged.

Private evidence directory: `needle-training/firmware-port-tests/cpu-comparison-20260923` in the development workspace. It contains configuration rollback bytes, boot logs, raw results, captures with hashes and the restoration record. Public readers do not need those private files to use AIEdge.
