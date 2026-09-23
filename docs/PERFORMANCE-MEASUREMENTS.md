# Test-board processing measurements

## Pending alignment preview optimization

The alignment stage encoded the raw frame into its preview buffer, then overwrote that JPEG with the annotated preview during the same successful stage. The local change removes the first encode and initializes/clears the cached preview length so a failed stage cannot expose an uninitialized or stale length. Rotation, alignment and the final annotated encoding remain in place. A test executes the actual method with image-operation substitutes and checks both alignment modes and temporary-image allocation failure. This establishes call/control behavior, not image parity or a measured speedup. On-device timing and preview checks remain pending.

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
# Saved-JPEG diagnostic, September 23, 2026

## 240 MHz comparison

The phased-memory diagnostic on build 2026-09-23 20:22:29 UTC passed three
consecutive saved-JPEG runs at 240 MHz: **19.254641, 19.281882, 19.286914 seconds**.
Every dial's feature tensor and output bytes matched its reference exactly.
The median **19.281882 seconds** is about **31.4% lower** than the three-run
160 MHz median of 28.098249 seconds on the same build.

The original configuration was restored byte-for-byte and a 160 MHz startup
was verified afterward. Temporary INFO logging was also restored. Image
archiving and automatic capture stayed disabled; no new image was captured.
The reported CPU temperature at the end of the 240 MHz run was 72 C; this is a
single sensor snapshot, not a sustained thermal qualification.

This is promising headroom for a 30-second cycle, not proof of that cadence.
The diagnostic excludes capture and publication, uses one saved image, and
does not establish real-image accuracy, long-term stability or network/archive
performance under load. Public firmware defaults were not changed by this test.

## Repeated-run follow-up

Repeated testing exposed an allocation failure in the diagnostic's original
buffer ordering. A first attempt to allocate its largest scratch buffer before
decoding instead left insufficient space for JPEG temporaries. Neither failure
is counted as a valid fast run. The corrected diagnostic loads reference vectors
only after preprocessing scratch is released, keeping these allocations apart.

On test build 2026-09-23 20:22:29 UTC at 160 MHz, three consecutive JPEG runs
passed exact feature/output checks: **28.104853, 28.098249 and 28.084552 seconds**
(median **28.098249 seconds**). This is a limited repeat check, not long-term
stability evidence. Settings remained unchanged; no camera cycle or upload ran.

The same candidate replaces unnecessary 360-element percentile sorts with
selection of the two required order statistics. Its 180 host per-dial results
match prior acceptance values, visibility scores and feature bytes exactly.
These timings show no meaningful total-pipeline speedup over the original
28.024-second observation; do not describe the candidate as meeting 30-second
capture cadence. It still excludes capture and result publication.

The test ESP32 processed an existing private 640x480 meter JPEG using its actual
stb decoder and shared PSRAM allocator, followed by marker registration, fixed
dial calibration, visibility checks, feature extraction and frozen inference.
All six feature tensors and inference outputs matched the decoder-specific
desktop reference bytes exactly. The existing RGB control also passed.

| Diagnostic | Total processing | JPEG decode | Alignment |
| --- | ---: | ---: | ---: |
| Saved JPEG | 28.024 s | 1.068 s | 3.557 s |
| Saved RGB control | 26.993 s | Not performed | 3.551 s |

These are one run each at the unchanged test-board CPU setting, not a sustained
benchmark. The JPEG total includes model setup and diagnostic comparison
overhead, but excludes camera capture, initial fixture verification and result
publication. It does not prove a 30-second capture cadence or reading accuracy.
The JPEG and RGB paths intentionally have different reference tensors because
desktop Pillow and firmware stb decoding differ slightly.

The JPEG diagnostic retains six feature tensors while releasing decoded image
and alignment scratch memory before loading the model. This prevents decoder
and model allocations from using shared PSRAM concurrently. No new camera image
was taken; automatic processing and image archiving remained disabled and the
test-board configuration was unchanged. This diagnostic firmware was installed
only on the test board; the public installer release was not updated.
