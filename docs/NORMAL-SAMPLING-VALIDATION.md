# Normal recognition sampling

The normal PolarV1 capture path now explicitly uses the same even-grid bicubic sampling and integer interpolation checked in saved-image ESP32 replay. It retains the frozen crop coordinates, needle pivots, model, three-marker alignment guard and visibility checks. Dense sampling remains available in replay comparisons. Debug cycle timing identifies `sampling=even_grid`.

September 23 local regression: 15 retained full frames, seven conditions (original, digital brightness plus/minus 15 percent, small translations and plus/minus one degree rotation), both sampling modes: all 210 frame evaluations passed alignment and all six visibility checks. Maximum circular difference between dense and sparse predictions across these conditions: 0.010893 on the 0-10 dial scale. These are synthetic variants of existing images, not independent labels or physical lighting tests.

Earlier test-board replay with this three-marker sparse algorithm took a median 14.36 seconds across 15 saved frames and matched frozen reference tensors and scores exactly. That replay does not measure the full camera, publication or archive cycle. The new normal-path call is installed on the test board, but its full camera-cycle performance still requires verification; sustained 30-second valid capture cadence remains unproven.

## Test-board deployment

Source `2c954f7`, bundle `0ab100fa3cbd9ec59d678a6f764c975eac98026be0efcd792693adcfcced94d8`, built September 24 at 03:40:19 UTC, passed managed OTA, restart and verified bundle selection. Saved configuration and website credentials remained unchanged. A post-install sparse saved-JPEG smoke test completed all six dials with exact reference tensor and score parity in 14.272808 seconds, with no camera cycles or archive worker.

The candidate also carries the previously built authenticated meter-profile metadata endpoint. Device checks confirmed authentication on GET/POST, rejection of missing or stale revisions and invalid profiles, and unchanged profile/configuration afterward. Profile activation and meter-type setup remain unfinished; the endpoint explicitly reports `not_integrated`.

Private evidence: `needle-training/firmware-port-tests/aiedge-normal-sparse-profile/{ota,profile-http,replay-smoke}`. This is a test-board development bundle, not a production-meter deployment or public installer release.

## Normal camera-path allocation check

A bounded test-board trial on bundle `e277163864b3093865c5ad2f8bffd40abceb9756e5a3fbe0bbe75370f18522a4` ran one actual camera cycle at 160 MHz with illumination off and external reporting disabled. Capture took 6.875065 seconds, the preceding alignment stage 3.886456 seconds, and the polar stage 2.084379 seconds before rejecting a weak marker match. The total failed cycle was 12.860928 seconds.

The normal runner loads/verifies the model, allocates its tensors and obtains the reserved workspace before marker matching. Reaching `Marker registration rejected: 3` therefore confirms those allocations succeeded while the normal RGB image existed. The test did not reach six-dial preprocessing/inference, produce a valid reading, or verify a 30-second successful cadence. Do not use the fast rejection as a performance success.

Saved-JPEG replay currently decodes/preprocesses before loading its model, so its 14.27-second result is not a direct measurement of the complete normal sequence. Normal capture overhead, valid full-cycle operation, external publication and archive load still require end-to-end verification.

The original configuration was restored byte-for-byte and verified after restart; the saved gas profile was preserved. Evidence: `needle-training/firmware-port-tests/normal-sparse-camera-20260923/{result.json,summary.json,pipeline-log.txt}`.

## Five normal-path surrogate cycles

September 24 test-board bundle `3898a8db23383d77ecf31b5cf19bd49968a6ef4c944d4d390167bcc18b1b3652` completed five saved-image substitutions through normal image acquisition, alignment and all-six-dial recognition at 160 MHz. Cycle times were 21.356, 21.214, 21.236, 21.221 and 21.240 seconds. Starts were 30.030, 29.987, 30.000 and 30.002 seconds apart; no failures, overlaps or missed schedule slots were reported.

Mean stage durations were 4.757 seconds for acquisition/decode/copy, 1.947 seconds for preceding alignment and 14.522 seconds for polar recognition. Across 25 status reads, median response time was 203 ms and maximum 344 ms. These sampled requests do not establish latency for every website operation.

The input was a retained real meter image re-encoded to fit the legacy 30 KB demo buffer; raw parent and derivative hashes are preserved. Repetition does not add accuracy evidence. Demo capture timestamps are intentionally invalid, accepted reader cycles remain zero, and publication and archival were disabled. This verifies bounded normal-path processing with the RGB image resident, not live capture-to-publication performance or physical consumption. Original configuration and profile were restored; temporary demo files were removed and absence verified. The cleanup wrapper initially hit a reset connection after reboot; fresh readback established the baseline before cleanup, and read-only reconnect handling has been added.

Private evidence: `needle-training/firmware-port-tests/normal-demo-cadence-01/{result.json,timing-summary.json}` and its `-preparation/restoration.json`.
