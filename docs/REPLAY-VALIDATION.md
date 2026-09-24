# Saved-image replay validation

September 24, 2026. Test-board bundle `31a3388e5eab85f826581187feae4b476a9726506cc17149f69dcfaa3c641339`.

All 15 archived JPEG frames completed on the ESP32, with exact feature-tensor and output parity for all six dials per frame (90 dial outputs). The frames were replayed once in their existing order using sparse sampling. No new labels, training data or accuracy measurements were created.

The board retained the same boot identity and configuration throughout. The normal camera loop made zero attempts, the archive worker remained disabled, and no production device was accessed. This isolates saved-image recognition; it is not a sustained capture-to-publication or archive-overlap test.

## Processing time

| Stage | Median seconds | Maximum seconds |
| --- | ---: | ---: |
| JPEG decoding | 0.735 | 0.755 |
| Alignment | 3.967 | 3.990 |
| Six-dial preprocessing | 7.179 | 7.217 |
| Six-dial inference | 1.764 | 1.774 |
| Other diagnostic work | 0.347 | 0.362 |
| Total | 14.001 | 14.044 |

Total times ranged from 13.925 to 14.044 seconds. The nearest-rank 95th percentile is 14.044 seconds; with only 15 observations, it equals the maximum. Per-stage medians need not sum exactly to the median total.

All 45 diagnostic-status requests succeeded. Median latency was 203 ms, nearest-rank p95 was 328 ms, and maximum was 359 ms. These timings cover that status endpoint, not every website page or operation.

## Limits and remaining checks

Numerical parity verifies compatibility with the frozen reference pipeline, not physical reading accuracy. Similar/stationary dial positions are not independent accuracy evidence. Camera capture, lighting, MQTT publication, simultaneous image archiving, cold-boot behavior and sustained 30-second scheduling still need their own verification. The test board reported camera unavailable at preflight; the saved-image diagnostics remain usable in that state.

Private evidence: `needle-training/firmware-port-tests/aiedge-alignment-ambiguity-01/full-replay/`, including the preflight, per-run results and polls, final summary and timing analysis. The separate host ambiguity fixtures verify rejection of exact/near duplicate peaks; this normal replay batch did not inject ambiguous markers on the board.
