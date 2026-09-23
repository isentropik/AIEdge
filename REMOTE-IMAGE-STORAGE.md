# Remote image archive requirement

User requirement: allow sending images to remote storage for future training.
This is part of the replacement firmware objective. A local receiver prototype
is implemented; the firmware spool/uploader and remote deployment remain pending.

September 22 destination clarification: the user wants a storage-server IP address
or hostname and folder path. The proposed transport is HTTPS to a small receiver
running on that server, whose configured absolute folder is the archive root.
This is not direct SMB/NFS support: an arbitrary network-share path alone cannot
be treated as an upload endpoint. Server software installation and the actual
destination still need to be established before deployment.

Capture and inference must not wait for the remote destination. Use a bounded
local spool and a separate upload worker with bounded timeouts/backoff. Explicitly
report spool exhaustion, dropped captures and failed uploads; do not claim every
frame was archived if storage or network limits prevented it. Retention/deletion
policy must be explicit, and remote success must be verified before deleting a
local pending copy. Upload retries use stable content identities to avoid duplicate
objects. The destination and credentials are not configured or authorized yet.

Archive full captured frames, with optional derived dial crops. Preserve original
image bytes, SHA-256, dimensions/encoding, monotonic capture time, boot identity,
and trustworthy wall-clock capture time when available. Retrieval/upload time is
not capture time. Include firmware/model/calibration identities and imaging-setting
identity so changes in geometry or lighting can be distinguished. Keep estimates,
quality/rejection reasons and human labels separate. Predictions must never appear
as confirmed training labels. All new images begin unreviewed and outside training;
deduplication and held-out split protections apply during later curation.

Choose a supported remote protocol/destination before live setup. A small HTTP(S)
receiver or object-store-compatible gateway can keep ESP32 memory and retry logic
bounded; do not assume the device can mount an arbitrary network share. Credentials
must not appear in images, filenames, logs or public metadata. Certificate and
authentication behavior require validation for the selected transport.

Acceptance includes successful upload and byte/hash readback, duplicate retry,
disconnect/reconnect, partial upload, server rejection, full spool, reboot during
upload, clock uncertainty and sustained capture/inference under upload load.
The 30-second cadence is a hardware target to measure with archival enabled.
No destination has been contacted and no images have been uploaded by this work.

## Local receiver prototype

Workspace scripts: `needle_reader_v2/image_archive_store.py` and
`needle_reader_v2/image_archive_receiver.py`. The CLI accepts `--bind`, `--port`,
`--folder`, `--token-file`, and optional `--certificate` / `--private-key`.
The folder is an absolute server-local path. The default listener is loopback;
binding beyond loopback requires TLS. A TLS reverse proxy may forward to loopback.
Tokens must be random URL-safe secrets, 32–256 characters, kept out of command
arguments and image records. Hostnames/IPs must match the TLS certificate when
the future firmware uploader validates its server.

POST `/v1/captures` carries original image bytes as `application/octet-stream`,
an exact Content-Length (maximum 2 MiB), a bearer token, and `X-Meter-Metadata`
containing base64 JSON (maximum 4096 header characters). Chunked/compressed
requests are rejected. Metadata schema is defined by `validate_metadata` in the
store; duplicate JSON keys and additional fields are rejected. It intentionally
does not accept human labels or treat an estimated reading as a label.

Successful new captures return 201, verified retries 200, conflicting identity
409, invalid requests 400, authentication mismatch 401, and storage failures 503.
Receipts identify both raw image and immutable record hashes. Clients must verify
the receipt matches their pending capture, not merely check the HTTP status.
Four workers and a 15-second connection deadline bound network work by default;
excess connections close for a later retry. TLS handshakes occur inside workers.
Filesystem calls can still block beyond the network deadline; use a healthy local
filesystem, not an untested network mount. This prototype is not yet production
validated or load-tested on the storage server.

Storage publishes via atomic hard links after file fsync and verifies readback.
The destination filesystem must support that operation. Directory entries are
not yet durably synced across every supported platform: receipt readback is not
a guarantee against sudden power loss. Failed writes never receive a success
receipt; an orphan content blob is safe to retry. New records are unreviewed and
training-ineligible. Image contents remain opaque bytes at this layer; image
validity, dimensions, geometry and split eligibility require later validation.

Local tests cover concurrent retries, distinct captures with identical images,
metadata conflicts, corrupt stored blobs, publication failures, authentication,
HTTP request validation, duplicate metadata keys and stalled-header expiry.
They use disposable local files and loopback HTTP only. Remote TLS, power-loss
recovery, long-running storage exhaustion and firmware integration are unverified.

## Firmware queue policy

`code/components/jomjol_flowcontroll/ImageUploadQueue.h` implements the portable
single-owner queue state machine. It is not yet connected to capture, disk spool,
HTTP transport, configuration or the scheduler. Its default limits are eight
entries and 8 MiB of referenced image bytes (payloads are not held in this queue).
Admission rejects new entries when full, retaining all existing entries. The
future capture adapter must report every rejected admission as an archive drop;
these constants do not establish adequate SD-card or RAM capacity on hardware.

Only one upload is active. Retryable failures use 5-second exponential backoff,
capped at five minutes. Round-robin selection avoids starving newer entries.
Request/authorization/conflict errors and invalid success receipts block the
entry for operator repair. Such entries retain their capacity and cannot be
silently deleted. A receipt must match capture, image and record identities,
schema version, readback verification and unreviewed/training-ineligible status.
HTTP success alone is insufficient. Attempt serials reject stale completions,
including responses referring to a reused queue slot.

Acknowledgment and release are separate: the future spool adapter must finish
local cleanup successfully before releasing a slot. On restart, rebuild pending
entries from the verified spool and retry stable identities; never restore a
monotonic retry timestamp from an earlier boot. Durable spool publication,
receipt JSON parsing, network certificate checks, authentication configuration,
blocked-entry repair and on-device telemetry remain to be integrated and tested.
The host C++ test covers 500 retries, byte/count limits, stale replies, identity
conflicts, fairness and receipt validation. It is included in the firmware
packaging test gate; this does not prove on-device archival or capture timing.

`ImageArchiveMetadata.h` defines the firmware's canonical capture metadata and
expected receipt identities. Device/boot names and hashes have restricted ASCII
formats; image length and monotonic timestamp bounds are checked before encoding.
Wall-clock capture time is either unknown (`null`) or a validated UTC timestamp
in `YYYY-MM-DDTHH:MM:SSZ` format, with Gregorian day/leap-year checks. The monotonic
integer timestamp is emitted directly, never through floating-point JSON values.
Firmware callers must supply a real SHA-256 implementation and hash the saved
image bytes before constructing a record; hashing failure clears the result.

`test_image_archive_metadata.py` compares actual C++ serialized hash inputs with
records written by the Python receiver store. All 21 cases agree byte-for-byte,
including timestamps immediately around 2^53 and at INT64_MAX, unknown UTC and
leap-day UTC. Invalid dates, unsafe names and failed hashes are rejected. This
establishes cross-language serialization parity, not persistence: the disk spool,
recovery reader and ESP32 SHA adapter remain pending.

`ImageSpoolRecord.h` now supplies the pending-record binary codec: a 496-byte
versioned body plus its 64-character SHA-256, totaling 560 bytes. It persists
capture identity inputs, capture timestamps, image length and image/firmware/model/
calibration/settings hashes. Fields have explicit little-endian integer encoding
and zero-padded string widths, independent of compiler struct layout. Decoding
requires exact size, version, checksum, zero padding and valid field semantics;
failure clears the output. No upload time, retry deadline or inferred label is
stored. The image payload must still be verified separately against this record.

Host tests pass 1,130 cases, including every truncation length, a changed byte at
every position, rehashed invalid fields, maximum allowed capture timestamp and
unknown UTC. The test uses Python SHA-256 as the callback oracle to isolate and
check the C++ codec; it does not exercise the ESP32 hash implementation, SD writes
or sudden power loss. Actual file publication, recovery enumeration and orphan
accounting remain required before claiming a restart-safe spool.

`ImageSpoolFile.h` implements combined-file publication: the 560-byte header
followed by exactly the original image bytes. It validates the input hash, creates
a temporary file exclusively, writes, flushes/fsyncs, closes, and reads back the
header and entire image before renaming. Final readback is required for success.
Image verification streams through a 4 KiB buffer. Existing final files are
verified as duplicates or rejected as conflicts/corruption; existing temporary
files are preserved, never silently truncated. Failed publication preserves its
temporary file for recovery accounting. A single spool owner must serialize all
operations: the rename logic is not safe for competing writers to the directory.

`ImageArchiveSha.h` provides incremental mbedTLS SHA-256 with checked errors.
The local file test compiles the actual installed mbedTLS software SHA sources
and covers real file publication/readback, retry, metadata conflict, corrupted
image, leftover partial file, trailing bytes, missing paths and hash lifecycle.
These checks pass on the host filesystem. They do not establish ESP32 hardware
SHA behavior, FAT rename/power-loss guarantees, directory durability, or sustained
30-second capture performance. Recovery enumeration, bounded admission including
orphans, upload/deletion, fault injection for failed sync/rename and capture
integration are still required. This code is not yet invoked by live firmware.

`ImageSpoolRecovery.h` adds a bounded startup scan (at most 32 directory entries)
and reconstructs a fresh upload queue only when the scan completes. It verifies
final filenames against capture identities and verifies image contents before
queue admission. Physical sizes of all files, including partial, corrupt and
unrecognized files, count toward the admission limit. Header bytes also count.
Incomplete scans prohibit new admissions and leave the previous queue unchanged.
Partial and damaged files remain visible as counts; nothing is silently deleted.
Healthy entries above queue capacity are reported separately for later recovery.

An explicit `promotePending` operation can finish publication after a verified
temporary file survived interruption. It refuses invalid capture names, damaged
files and conflicts, and verifies the final file after rename. Both operations
require the dedicated directory's single owner; startup sequencing and worker
locking are not yet connected. Tests cover successful pending-file promotion,
partial-file rejection, queue reconstruction, corruption counts, missing-folder
failure, scan limits and admission including overhead. Actual ESP32/FAT recovery
and injected I/O failures remain unverified.

`ImageArchiveReceipt.h` parses a bounded (1024-byte) flat receiver response using
cJSON. It rejects missing/duplicate/unknown fields, wrong types, invalid hashes,
non-verified receipts, training-eligible records, escaped aliases, embedded NULs
and trailing JSON. Capture/image/record identity matching remains a separate
queue check. Tests compile the actual installed cJSON source and pass 393 cases,
including real receiver-generated initial/retry receipts, every truncation and
syntactically valid receipts for the wrong capture or content.

`removeAcknowledged` requires a matching acknowledged queue ticket, verifies the
current complete spool file against that identity, removes it, and only then
releases queue capacity. Changed/corrupt files or failed removal retain their
queue slot. Local tests cover rejection before acknowledgment, successful cleanup
and corruption after acknowledgment. A crash after successful removal but before
queue release is recovered by directory enumeration on the next boot. This does
not establish power-loss durability of either server acknowledgment or SD removal.

## ESP32 upload transport

`ImageArchiveTransport.cpp` implements one upload attempt using ESP-IDF's HTTP
client. It accepts a DNS hostname or IPv4 address, port, trusted PEM certificate,
and bearer token; the receiver's server-local folder is configured on the server,
not supplied as an arbitrary per-request write path. IPv6 literals are not yet
supported. The endpoint is fixed to `/v1/captures`, HTTPS is mandatory, certificate
hostname checks stay enabled, and redirects are disabled to avoid forwarding a
credential to another destination. No credentials are logged by this code.

Before opening a connection it verifies the spool and ticket identity. It sends
base64 canonical metadata plus original image bytes streamed from disk in 4 KiB
blocks, handles partial writes, and rechecks the sent payload hash. Response size
is bounded to 1024 bytes and only complete, parsed, matching receipts succeed.
RAII closes files and the HTTP client on failure; this function never removes
the source. A monotonic deadline is checked between operations, with the remaining
budget set as the SDK timeout. DNS/TLS internals and filesystem stalls still need
hardware validation; this is not a proven hard deadline for every blocking call.

The transport host test compiles the actual uploader with the installed software
mbedTLS/cJSON sources and fault-injected HTTP/clock APIs. Fourteen outcomes cover
successful initial/retry status, client/header/open/write failures, response-header
failure, server rejection, oversized/incomplete/failed/malformed responses,
deadline expiry and timeout-configuration failure. Invalid destinations are rejected
before client initialization, partial writes are exercised, and every outcome
retains its spool file. This is not an actual TLS/network test or server deployment.
Worker scheduling, configuration UI and capture integration remain pending.

## Worker coordination implemented locally

`ImageArchiveEngine.h` connects recovery, bounded admission, file publication,
queue attempts, receipt acceptance and cleanup. A fresh inventory before admission
includes unknown/partial files without replacing the live queue or resetting its
retry deadlines. Local tests exercise failure then retry, admission during backoff,
successful cleanup, restart reconstruction and blocking an invalid success receipt.
Inventory currently rereads verified files; SD throughput needs profiling before
assuming this cost fits the desired cadence.

`ImageArchiveWorker.cpp` places that engine in a low-priority FreeRTOS task.
Startup configuration is immutable for its lifetime. It has a one-entry inbox
and one reserved PSRAM image allocation (at most 2 MiB); capture submission copies
bytes and never performs disk/network operations or waits on a queue. Memory or
inbox exhaustion rejects the capture and increments a drop counter. The worker
frees the image allocation after its storage attempt, before uploading. Task stack
is provisionally 24 KiB; hardware memory availability/high-water marks must be
measured. The worker is not started automatically and is not yet called by capture.

Handoff success is not durable storage success: power loss before the worker saves
an inbox image can lose that image. Status separately exposes handed-off, dropped,
stored, rejected, uploaded, failed, cleanup-failed, pending and blocked counts.
The counters are currently RAM-only. A failed initial scan leaves the worker
unready; automatic recovery from that condition and runtime reconfiguration remain
to be designed. The worker does not silently remove damaged or partial files.

The actual worker compiles in host fault tests with deterministic RTOS/PSRAM
substitutes and real spool/crypto code. Five scenarios cover success with a busy
inbox rejection, queue creation failure, task creation failure, PSRAM allocation
failure and queue-send failure; ownership cleanup and counters are checked.
These are not real FreeRTOS concurrency, TLS, PSRAM-pressure or camera-timing tests.

## Original-frame capture hook

`RawCaptureObserver.h` provides a startup-only optional observer, invoked by
`CaptureToBasisImage` while the original camera framebuffer is still owned.
Notification happens only after decode/dimension checks and successful light-off,
and only for a valid live driver timestamp. Demo images and rejected captures do
not trigger it. The frame is returned on both success and the relevant failure
paths. No second capture or recompression is introduced. Observer callbacks must
copy borrowed bytes synchronously if needed and may not do disk/network IO.

The actual capture-body host tests pass all 14 existing cases, with additional
checks of original byte identity, timestamp, callback count, light state and
suppression on failures/demo/invalid time. The archive worker is not yet registered
as this observer: startup configuration must first establish device/boot identity,
actual firmware/model/calibration/settings identities, and handling of later
imaging-setting changes without stale metadata. Unlabeled files must not silently
claim they came from a calibration/configuration that was no longer active.

## Capture-settings descriptor

The observer now receives a versioned descriptor captured under CameraAccess
before framebuffer acquisition. It records all 28 fields in the current camera
driver status structure, ten capture configuration fields (including zoom),
master duty, flash delay, pixel format and camera clock. Lighting configuration
includes configured channels, pixel count, bytes per pixel and GPIO modes, or
the built-in PWM/digital path. This is driver-reported/configured state, not
register readback or measured illumination. Changes during automatic exposure
are not independently measured by this descriptor.

The host snapshot test verifies coverage against the actual camera_status_t
definition and verifies every recorded driver/configuration field changes the
descriptor independently. Lighting inputs and missing-lighting rejection are
checked. Capture-body tests verify the descriptor reaches the callback with
the original frame. The descriptor is not yet persisted or uploaded; binding it
to settings_sha256 and preserving a retrievable settings record remain necessary.
The observer remains unregistered and no live archiving is enabled.

## Receiver settings dependency

The receiver now accepts authenticated POST `/v1/settings`, with original
descriptor bytes as `application/octet-stream`, exact Content-Length (at most
8192), and `X-Settings-SHA256`. It validates the version prefix, bounded ASCII
encoding and exact SHA-256, writes an immutable `settings/<hash>.txt`, and returns
a readback-verified receipt with version, settings hash and duplicate status.
New records return 201, matching retries 200, and conflicting stored bytes 409.

The HTTP capture endpoint now requires and revalidates the referenced settings
record before publishing a capture; absent/corrupt settings return 409 and no new
capture is acknowledged. The low-level store_capture helper remains available
for isolated storage/serialization tests without dependency enforcement. This
HTTP protocol change is local only: the firmware uploader does not yet send the
settings request and therefore is not ready for end-to-end use with the updated
receiver. Implement sender ordering and settings spool persistence before enabling
the worker. Seven loopback receiver tests pass, including missing dependency,
settings retry, corruption and invalid/oversized descriptor cases. No remote
server has been changed or contacted.

`ImageArchiveSettings.h` now provides firmware descriptor validation and strict
settings-receipt matching. Receipts must have exactly the four expected fields,
correct types/version, verified readback and the expected settings hash; unknown
fields, duplicates, truncation, escaping, NULs and trailing content are rejected.
The existing cJSON host harness now passes 159 settings-receipt cases in addition
to 393 image-receipt cases, using real receiver-generated settings receipts.
Descriptor validation checks the bounded versioned ASCII format and hash callback
failure. Settings persistence and transmission remain to be connected; receipt
validation alone does not enable end-to-end settings upload.

## Local settings persistence

`ImageSettingsFile.h` implements immutable `<hash>.settings` files with exclusive
temporary creation, flush/fsync, bounded readback, hash/descriptor validation and
rename. Reads clear their output on corruption or failure. Matching existing
files are duplicates; damaged files are preserved and rejected. A complete
verified `.settings.pending` file can be promoted on retry, while a partial file
is preserved. The validation-only descriptor helper now lives separately in
`ImageSettingsDescriptor.h`, without a JSON-library dependency.

Real local-file tests with software mbedTLS pass for creation, duplicate retry,
readback, recovery before rename, trailing corruption, invalid path/hash input
and partial-file preservation. Receipt regressions still pass (393 image and
159 settings cases). These helpers are not yet invoked by capture/worker or the
uploader. Admission must account for settings and pending files, and cleanup must
preserve any descriptor referenced by queued images. The current spool inventory
counts all files physically but does not yet classify settings files separately.
No hardware SD or power-loss durability claim follows from these host tests.

## Settings-first firmware upload ordering

The ESP32 uploader now requires a verified local settings file, POSTs its original
descriptor bytes to `/v1/settings`, and requires a matching verified receipt before
opening the image request. Settings failures return without sending image bytes.
The settings request uses the same authenticated HTTPS destination, certificate
checks, redirect prohibition and bounded response parsing. Retries resend settings
idempotently rather than assuming the server still retains an earlier upload.

The current timeout budget applies separately to each request: the settings and
image phases may each consume the configured budget, plus local validation and
SDK blocking overhead. This is background work, not a proven capture deadline.
All 28 host fault scenarios pass across both phases; source files remain intact
and a missing local settings record prevents client initialization. Host network
APIs are simulated, so real HTTPS interoperability remains to be verified.

Capture/engine admission still does not write a settings descriptor automatically.
That integration and settings storage accounting/cleanup are required before
enabling the observer and worker; the uploader intentionally refuses images whose
settings dependency is missing. No server or live firmware changes were made.

## Worker settings handoff connected

`submitArchiveImage` now requires the capture descriptor and copies it into the
single pending job. The engine validates its hash against capture metadata,
reserves byte/file capacity for a new descriptor plus the image, and publishes
the settings file before the spool file. Descriptor failures reject admission;
queued duplicates require an intact matching settings file. A partially completed
admission may leave a settings file, which the existing inventory counts against
capacity rather than ignoring. Images and descriptors remain unreviewed.

Worker tests verify that a matching descriptor is readable before the mocked
uploader is invoked. Admission tests cover settings overhead at byte/file limits,
while existing retry/restart and handoff-failure tests continue to pass. Settings
files are currently retained after image cleanup, so varied settings can eventually
fill the bounded spool. Reference-aware cleanup and dedicated settings inventory
classification remain required before enabling live archive capture.

## Reference-aware settings cleanup connected

After an acknowledged image is verified and removed, the engine now attempts
cleanup of its settings hash. A bounded, complete directory scan must validate
every classified file and find no reference from either a final spool file or
a fully written pending spool file. Partial/corrupt/unknown entries, scan limits
or read errors defer deletion. The descriptor is revalidated before removal.
All operations require the existing single-worker ownership contract.

Tests verify retention while another image shares the settings, deletion after
the final acknowledged image, retention for an interrupted valid spool, and
deferred deletion when that spool is damaged. Worker regressions still pass.
Deferred cleanup has a separate RAM counter; orphan cleanup after unrelated
failures or power loss is not yet automatically retried. Such files continue to
count against capacity. Remote settings records remain immutable and retained.
This is host-verified behavior, not a guarantee of SD-card power-loss durability.


## Directory durability follow-up

The receiver now fsyncs parent and object directories on POSIX after directory
creation, hard-link publication and existing-object retries. Ancestors are revisited
so a previous failed directory sync cannot turn into a successful retry solely
because the path exists. Sync errors propagate; no success receipt is returned.
The server account must be able to open/sync those directories. Windows retains
file fsync plus verified readback because this implementation has no portable
Windows directory-flush primitive. Receipts do not promise power-loss durability
on either platform or unverified NAS/controller behavior.

Store fault tests cover failed directory sync, preserved orphan blobs, retry sync
and nested-directory publication. Receiver and generated local TLS setup tests
also pass. POSIX calls are fault-injected in Windows tests; actual server testing
remains required. Candidate k contains the preceding receiver version; the next
package must include these companion changes. No live server or meter was changed.
