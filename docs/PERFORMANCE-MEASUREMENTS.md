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

## Normal-camera rejection trial

A separate trial loaded the exact frozen six-dial geometry and ran one normal camera cycle, with no MQTT or external publication configured. Capture/decode completed in 6.715304 seconds, the inherited alignment/preview stage in 3.879307 seconds, and the Polar stage rejected missing/mismatched markers after 1.362992 seconds. The whole rejected cycle was 11.967956 seconds, with zero accepted readings. This is rejection-path evidence, not successful recognition performance; its short duration must not count toward the 30-second target.

Startup removed the obsolete `FlipImageSize = false` line. The test detected that baseline change, verified it was the only change, and restored the original configuration byte-for-byte followed by a verified reboot. Private evidence is in `normal-pipeline-trial-20260923` beside the CPU comparison.

The trial exposed an incorrect success summary: the outer `doflow` wrapper discarded the controller's false return and always returned true, while the scheduler always logged a completed round. The source fix preserves the controller result and separately reports completed, failed, and skipped/busy rounds. Actual-wrapper/reporting tests, 12 controller regressions, and the final ESP32 build pass. The board returned on COM8; its MAC matched before any write. Loader 0.1.11-test7 installed the verified private candidate, and the application booted with its camera available. The normal-camera retest recorded one rejected cycle (12.015284 seconds), zero accepted/completed cycles, and the corrected warning `Round #1 failed (12 seconds)`. Earlier incorrect completed entries remain historical log records. This still does not establish successful reading accuracy or cadence. The original configuration was restored byte-for-byte after the trial. Recorded installation: `recorded-20260923T171859Z`; cycle evidence: `normal-pipeline-outcome-retest-20260923`. The temporary package server and board-only firewall rule were removed. This test-board deployment is not a public installer release.
