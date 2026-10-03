# Performance diagnostics

The existing diagnostic download now includes bounded duration statistics for
the current app store session. Nothing is written to the SD card or a telemetry
file. Counts reset after an app restart. At most 64 observations are kept per
stage; p95 uses the nearest rank of each outcome's retained samples.

Success, failure, rejected recognition and duplicate frame admission are
separate. A successful inference means the decoder produced an estimate; it
does not establish a valid physical total or independently verified accuracy.
No camera address, credentials, image/hash, dial reading or exception text is
included in the timing report.

All durations use the app host's monotonic clock. `camera_headers` measures
request start to response headers, including connection setup, camera work and
network time. It does not isolate the camera exposure. `camera_download` covers
reading the JPEG body and assembling its bytes after valid response headers.
Reference/preview captures use separate stages from normal captures.

`storage` includes admission validation, existing-image integrity checks,
writing/fsync where needed and database commit. `image_validation` is its
metadata/hash/envelope validation subset. New capture events with an already
saved JPEG are admitted normally; retrying the same frame is a duplicate.

`recognition` measures one admitted image's processing and inference commit.
`read_and_infer` covers verified-image read, JPEG decode, alignment, feature
sampling and model inference. `inference_commit` covers durable result commit.
An alignment/decode/model rejection is retained as rejected recognition rather
than a fast successful reading. Existing `total_processing_seconds` retains its
original scope and is not relabeled as end-to-end time.

Stages overlap and must not be summed. Missing samples are not zero. Timing
counts describe attempted operations, not independent needle positions.
Recognition queue waiting, camera-internal stages, consumption accounting and
MQTT publication are explicitly unmeasured. No cross-host UTC subtraction or
JPEG-byte division is presented as network throughput.

This local candidate changes recognition source bytes, which are part of the
consumption engine fingerprint. A later reviewed update must account for a new
relative consumption segment; old records remain preserved. Reader identity,
models, calibration and physical conversion logic are unchanged. This is not
included in the pending dev21 deployment approval and has not been deployed.
