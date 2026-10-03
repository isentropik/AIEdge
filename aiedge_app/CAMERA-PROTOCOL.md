# Remote camera protocol, version 1

`POST /api/v1/capture` with an empty JSON object requests exactly one fresh JPEG.
The server supports either `Authorization: Bearer TOKEN` for a token-capable camera
or Basic authentication using configured camera username/password. Choose one.
The AIEdge firmware route uses the existing website authentication gate (username
`admin` with the device password); it does not implement Bearer tokens. Credentials
over HTTP are suitable only for a trusted private network; TLS is needed against
network eavesdropping. The development open-website build bypasses that gate and
is not a secure release. No credentials are forwarded to redirects. The
camera owns lighting, exposure settling and acquisition as one serialized job.
No other request may change lighting midway through it. A busy device returns
409 or 503; the server records the miss and does not blindly retry a capture.

Success is `200 image/jpeg` with Content-Length and these headers:
- X-AIEdge-Frame-Id: unique ID, stable when retrieving that same acquisition
- X-AIEdge-Captured-At: timezone-qualified ISO 8601 actual capture time
- X-AIEdge-SHA256: lowercase SHA-256 of the JPEG bytes

IDs use 1-128 ASCII letters/digits, underscore, dot or hyphen. The server rejects
missing/invalid metadata, duplicate provenance or framing headers,
oversize/truncated bodies, redirects, future timestamps and hash mismatches.
Content-Length must be a single canonical positive decimal length; chunked
transfer encoding is outside this protocol. Device receipt or download time must never substitute for
capture time. Unsynchronized cameras must report failure instead of inventing time.
A repeated frame ID with different bytes, timestamp or clock metadata is a protocol error.

For restart-safe elapsed-time checks, a camera may also send this pair:
- `X-AIEdge-Clock-Id`: an opaque monotonic-clock epoch ID, using the same allowed
  characters and length as a frame ID. It must change whenever that clock resets,
  including every device reboot. It is not the device name or a permanent MAC ID.
- `X-AIEdge-Capture-Monotonic-Us`: the acquisition timestamp on that clock, as a
  canonical nonnegative decimal integer no greater than 9223372036854775807.

Send both headers or neither. Duplicate headers and partial/invalid pairs are
rejected. The app stores these fields unchanged with the acquisition; retries must
supply the same metadata. It never extracts a clock ID from a frame ID or fills in
missing times from receipt timestamps. Existing records remain unchanged and can
still be used for recognition without this pair.

The local timing gate requires the same camera and clock epoch, increasing ticks,
and UTC elapsed time agreeing within 250 milliseconds plus 200 parts per million
of the monotonic interval. A reboot, backward tick or larger UTC discontinuity
requires a new accounting anchor. The allowance is a conservative software rule,
not measured hardware clock accuracy. Even a continuous interval does not prove
that no wheel revolutions were missed. Consumption and flow are not yet published.
The local ESP32 route now emits this pair. Its clock ID is a random 128-bit boot
epoch shared by captures within that boot; the tick is the same sensor acquisition
timestamp used to calculate UTC. These local firmware changes are not deployed.
The actual route was compiled on the host with substituted SDK/camera/hash/clock
services and passed same-boot, reboot, replay and response-failure checks against
the app parser and capture ledger. Hardware timing validation remains pending.

Header, JPEG and HTTP error-body reads share a 20-second monotonic I/O deadline;
individual socket waits are capped at five seconds. Continuous trickle traffic
does not extend that deadline. DNS still uses the operating-system resolver;
this wrapper cannot interrupt a resolver blocked inside the operating system.
TLS keeps normal certificate and hostname checks. The public certificate/key in
`test-fixtures` is used only by isolated loopback tests and is excluded from the
Docker build context; runtime never adds it to the trusted certificate list.

The MVP is pull-based: the server schedules capture, never overlaps calls, and
skips missed slots instead of building a queue. Outage buffering and fetch-by-ID
are future additions. Existing r60 must not be described as compatible yet.

Local firmware implementation (not deployed): the route runs one asynchronous
camera job, holds the existing camera/light lock, settles illumination, discards
one buffered frame, and rejects a frame timestamp older than the settled time.
It requires an NTP synchronization observed this boot and rejects clock steps
across acquisition. It hashes the exact oriented JPEG bytes. The 2.5-second
settling period is currently fixed. Hardware timestamp semantics, responsiveness,
and end-to-end cadence remain unverified. The normal full-reader target retains its recognition loop. The separate
`esp32cam-managed-remote-camera` target loads camera/light configuration without
starting the reader task and rejects recognition diagnostic jobs. It preserves
the existing managed bundle and authenticated website/update path; SD assets are
still required. It is a migration build, not a new minimal camera distribution.
Its camera-specific OTA policy requires three consecutive fresh JPEGs successfully
sent, synchronized capture timestamps, readable settings, a verified bundle and
no system faults. Transmission success does not prove server persistence or meter
accuracy. Hardware startup, OTA rollback and 30-second cadence are unverified.

## Temporary Auto trials - local contract, not deployed

The app requires `GET /temporary-capture-capabilities` to advertise version 1,
remote-camera mode, OV2640, a 640 × 480 frame, temporary controls, restoration
before response, zero SD writes and a cooperative 20-second capture limit.
The trial route is `POST /api/v1/capture/temporary`, authenticated by the same
website gate as normal capture. Unsupported firmware cannot silently substitute
sensor automation for this contract.

The canonical compact JSON request contains the saved configuration SHA-256,
a random request ID, master lighting intensity and the nine supported image
controls. Unknown/duplicate keys, wrong types and values outside the strict
ranges are rejected. Light color, pixel type, count and selected GPIO remain
unchanged. Temporary controls are applied only in RAM. The worker settles the
sensor, discards a buffered frame and restores the saved controls and switches
lighting off before returning success. Restoration failure inhibits both normal
and temporary remote captures. Trial shots never count toward OTA acceptance.

The JPEG has normal capture provenance plus a request hash, saved/restored
configuration hashes and receipts for restored settings, lighting off and zero
SD writes. The app verifies all receipts, framing, exact image hash, synchronized
capture time and orientation. It uses a separate 25-second absolute I/O deadline
for each trial; cleanup and transmission can outlast the firmware's cooperative
limit. Neither limit can preempt an SDK stall or the OS DNS resolver.

Before each trial or final save, the app durably records a SHA-only intent bound
to the camera origin and known configuration revisions. It never stores camera
credentials or raw configuration in that record. A lost/invalid response leaves
the intent and blocks further captures across restart. Read-only status/settings
requests and switching Auto off cannot clear it. Explicit recovery activates a
known old/new saved revision on the same camera, verifies readback and activation,
and never resubmits the uncertain trial or save.

Auto uses at most eight probes over 90 seconds. It searches light and fixed
exposure with gain zero, then performs one combined configuration save if needed.
Activation of light and image controls must agree with the same exact revision.
Only a subsequent normal capture with verified provenance and acceptable image
quality can replace the reference. An orientation change also requires matching
reference/calibration before scheduled capture resumes. App shutdown stops new
probes and avoids starting a final reference after an in-flight commit finishes.

Original successful, rejected and partial JPEG bytes are retained with hashes
under `auto-trials`, outside reading history and inference. The archive is limited
to 128 runs and 256 MiB with a free-space reserve; nothing is deleted automatically.
Trial images are excluded from training and accuracy evidence. The quality
thresholds do not measure sensor noise or prove correct meter readings. Host and
browser substitutes do not establish physical dimming, startup or recovery.
