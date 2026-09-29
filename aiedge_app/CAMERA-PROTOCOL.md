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
missing/invalid metadata, oversize/truncated bodies, redirects, future timestamps
and hash mismatches. Device receipt or download time must never substitute for
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
The current local firmware route does not yet emit this optional pair; hardware
support and timing validation remain pending.

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
