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
