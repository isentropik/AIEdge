# Performance diagnostics

The diagnostic download reports bounded, in-memory durations. At most 64
observations per stage and 64 private capture correlations are retained. It
adds no telemetry files or SD writes. Counts and correlations reset after an
app restart. Missing, historical or evicted samples are never replaced with zero.
The report contains no camera address, credentials, image/hash, event identifier,
dial reading or exception text. p95 uses nearest rank within retained outcomes.

`camera_headers` measures request start to response headers, including connection
setup, camera work and transport. `camera_download` covers JPEG body reading and
assembly. Reference/preview captures have separate stages. `storage` includes
validation, image integrity checking/writing/fsync and database commit;
`image_validation` is its validation subset.

`recognition_queue_wait` covers same-session admission through dispatch of a new
inference, including worker scheduling, lock and lookup delays. Reused inference
does not create a new inference waiting sample. Old captures after restart have
no admission clock and are not assigned one. `recognition` covers verified-image
read, decode, alignment, feature sampling, inference and result commit.
`read_and_infer` and `inference_commit` are subsets. Existing durable
`total_processing_seconds` retains its original scope.

`accounting` covers an available inference's consumption/absolute calculation and
durable decision, while holding the existing coherent interpretation locks.
Idle polling and waiting for an inference are excluded. Decisions without an
estimated absolute reading are kept under rejected, including unresolved
whole-turn ambiguity. This does not discard those original durable decisions.

`mqtt_publication` measures a publication pump attempt, including any connection,
discovery and required acknowledgement delays. Unchanged readings are duplicates;
stale, missing, inconsistent or ambiguous readings are rejected. Failed broker
acknowledgements are failures and never become successful reading samples.

`capture_request_to_broker_ack` uses only the app host's monotonic performance
clock. It starts just before the normal scheduled capture request, after its
passive readiness check. It ends after the reading, attributes and online
availability are acknowledged by the broker. The exact event and source image
must match a retained same-session capture. This includes acquisition, transfer,
storage, recognition/consumption waiting and publication waiting. It records at
most once per capture event, even after reconnect or Home Assistant birth.
Manual uploads, old history and evicted captures have no complete sample.

Stages overlap and must not be summed. A broker acknowledgement does not prove
Home Assistant entity receipt, physical accuracy or the camera's internal capture
duration. Those remain unmeasured. No cross-host UTC subtraction or JPEG-byte
division is presented as network throughput. Counts are operations, not
independent needle positions; generated fixtures are not real-image accuracy.

Reader identity, models, calibration and physical algorithms are unchanged from
dev23. Recognition and consumption source bytes participate in the consumption
engine fingerprint, so deployment needs a reviewed separate relative segment
while retaining old records. This candidate is not part of the pending dev21
deployment proposal and has not been deployed.
