# When image delivery fails

Archiving is optional and runs separately from meter recognition. A saved image
is removed locally only after a matching server acknowledgment has been verified.

| Result | Behavior |
| --- | --- |
| Connection failure, HTTP 429 or HTTP 503 | Keep the saved image and retry with backoff. |
| HTTP 401/403 or another permanent request error | Keep the image blocked for attention; do not repeatedly send it in the running process. |
| Success response with a missing or mismatched acknowledgment | Keep the image blocked. HTTP success alone does not prove storage. |
| Worker busy or unable to allocate a capture buffer | Refuse the new archive handoff; recognition is not made to wait for upload. |
| Full or damaged local storage | Reject new saves. Preserve existing evidence; do not automatically format or delete it. |

Retry delay starts at 5 seconds and increases to a maximum of 5 minutes. Queue
recovery after restarting can attempt retained records again. These are not
guarantees of eventual delivery when the receiver, credentials or storage remain
unusable.

The status page now exposes **Captures not queued** and **Queued captures not
saved**, alongside saved images, acknowledgments and upload failures. A rejection
counter does not prove whether an interrupted write left a recoverable file.
Counts apply to the active destination and current boot, not lifetime totals.

September 23 host checks ran the actual archive worker with simulated connection
failure, rejected credentials, a mismatched success receipt, HTTP 503 and HTTP 429.
Every case retained a verified spool record and its settings; image RAM was freed
before network work. Transient failures remained pending and credential/receipt
failures became blocked. The UI tests cover skipped-capture warnings and clearing
stale counts when status cannot be read. This is deterministic host evidence, not
physical network-outage, SD power-loss or sustained cadence validation.

The additional UI counters are deployed to the test board in bundle
`ced4642ee9e563608b90e366c6fd8cb825af5e4ac189b4a1a21648f86da79e9d`.
OTA and reboot verification passed with configuration and password unchanged.
Both served asset hashes matched the package; a DOM fixture loaded the served
script against actual device status and displayed both counters correctly.
Archiving remained disabled. This was not a browser layout test. Rendered
verification remains pending, and earlier successful HTTPS delivery does not
establish these failure scenarios on hardware.

Private deployment evidence is in `aiedge-archive-counters-candidate/ota` and
`aiedge-archive-counters-candidate/asset-verification` under firmware-port-tests.

## Cannot connect to the storage server

If the page reports a secure connection failure and HTTP status is zero, the
receiver has not returned an HTTP response. This does not identify the cause:
the address, network route, firewall, certificate, or receiver may need attention.

1. Confirm the receiver is running and listening on its LAN address, rather than
   only `localhost`. Use that same address or name in AIEdge.
2. Check whether the receiver records a connection from the device. A successful
   upload from the receiver computer itself does not prove the ESP32 can reach it.
3. If no connection arrives, check the network route and inbound firewall policy.
   Any necessary allow rule should be limited to the receiver port and the device
   address or trusted network. Keep the firewall enabled.
4. If a connection arrives but HTTPS fails, check the configured CA, certificate
   validity, device clock and certificate name against the configured server name.
   Keep certificate verification enabled.
5. After correcting the cause, verify a matching upload acknowledgment and the
   stored image. A reachable status page alone does not prove image delivery.

## Interrupted receiver process

`tools/image-archive/test_process_interruption.py` terminates a child receiver
storage process with `os._exit` at three boundaries: after committing the image
blob, immediately before linking the capture record, and immediately after linking
that record. No success receipt is produced by the interrupted process. Retrying
preserves the original image and produces one verified, unreviewed capture record;
conflicting metadata cannot overwrite it. These cases passed on local Windows
storage on September 23. They are also part of the receiver's normal unittest
discovery command.

Unfinished `.pending-*` files are intentionally preserved. They are not capture
records, acknowledgment evidence or training data. This test does not establish
physical power-loss durability, network-share semantics or ESP32 retry behavior.

## Interrupted HTTP upload and lost acknowledgment

The receiver HTTP tests also exercise actual loopback sockets. A client that
sends only part of its declared image body and disconnects receives no success
receipt and leaves no image or capture record; a complete retry succeeds. When
the receiver commits the record but the connection is deliberately closed before
its acknowledgment is sent, the retry returns the same capture identity as a
verified duplicate. Exactly one record and one unchanged image remain, excluded
from training. All eleven receiver HTTP tests passed on September 23, including
the two deadline-handler tests now included by direct script execution as well
as unittest discovery. These are host network tests, not an ESP32 outage trial.


## Full disk between image and capture record — September 24

A loopback HTTP regression injects ENOSPC when publishing the capture metadata,
after the image blob is already stored. The response is HTTP 503 without a
verified-readback receipt. The complete original blob remains, no capture record
is published, and normal exception cleanup removes temporary files. After the
fault is removed, retry returns 201 with verified readback and creates exactly
one record without another image blob; a later identical retry returns 200.
All twelve receiver HTTP tests pass.

The current device queue acknowledges only a matching receipt on HTTP 200/201.
HTTP 503 follows its pending retry branch with increasing delay capped at five
minutes, so that response does not authorize payload deletion. Queue host tests
also pass. This combines receiver fault injection and queue code/host evidence;
it is not a physical full-disk or ESP32 network-outage test.


## Camera-only startup failure: queued-upload recovery

A prepared firmware change starts destination-bound queue recovery when camera
initialization alone fails (with optional noncritical camera-framebuffer/NTP
warnings). It does not initialize recognition or bind a capture observer. A
storage, memory, bundle or other critical error still blocks this recovery path.
Normal capture can bind later only with the required frozen profile and unchanged
archive destination/identity. Existing queued records retain their original
metadata and destination namespace; no legacy unbound queue is adopted.

Actual startup-source host tests passed for capture-disabled recovery, repeated
startup, changed destinations, missing profile, later binding and re-disablement.
The boot-branch fixture verifies critical-status combinations and processing,
camera-lock and storage guards. The full host/UI suite and clean managed ESP32
build passed for local candidate `aiedge-archive-camera-recovery-02`, bundle
`99f393258c9ca08caf33092ab771e61dcdad0f1b7fa8e5884195d0a8177c4ed0`.
This candidate is not deployed or hardware-verified. Its archive companion files
were found to come from an older private workspace copy; do not distribute that
package. The local builder now selects public archive sources, includes their
87-test suite, and verifies source bytes remain unchanged. A replacement package
and test-board validation remain pending. No real-image transfer to the new share
is implied by these checks.


The replacement candidate `aiedge-archive-camera-recovery-03`, bundle
`b12fd280a9c6c3f6f2f0f7796f749275233acc21ea7f6f48b52e382ebf570095`,
passed the full package checks and a clean build, then managed OTA and authenticated
boot verification on the test board. All eleven packaged archive companion files
match the current public tools byte-for-byte. Configuration, display profile and
password protection were preserved. Archiving remains disabled with zero camera
attempts. The synthetic device-to-SMB trial stopped during read-only preflight:
Windows denied creation of the temporary inbound firewall rule and a missing-file
preflight request disconnected. No archive settings were changed and no receiver
was started. Camera-independent recovery is compiled and deployed but its physical
upload behavior remains unverified. Host-to-SMB synthetic HTTPS checks remain the
only completed network-share delivery test. Production was not changed.


## Receiver process interruption on SMB — September 24

The three abrupt receiver-process termination cases now also pass when the
Windows receiver writes to an SMB storage share: after publishing the image
blob, immediately before publishing its capture record, and immediately after
publishing that record. Each interrupted process exited without returning a
receipt. Retrying preserved the original bytes and produced exactly one capture
record and one image blob. Another identical retry was a verified duplicate;
conflicting metadata was rejected without changing either object. Incomplete
pending files were retained unchanged, and all three archives passed the
read-only integrity audit, including the referenced settings descriptor.

This trial used synthetic bytes and fabricated metadata in a new isolated folder.
No camera data, labels, credentials, device configuration or training inputs were
changed. Evidence is retained privately under
`synthetic-smb-interruption-bd3ce3503ee2478bb89a10d8191185b8` in firmware-port-tests.
It verifies Windows receiver retry behavior on that SMB path, not ESP32 delivery,
HTTP/TLS recovery, a disconnected share, physical power loss or server-side
write durability. Those remain separate checks.


## Corrupt archived files and early full-disk failure — September 25

Three additional loopback HTTP regressions verify that a retry cannot acknowledge
or overwrite a corrupt existing image blob or capture record. Both return HTTP
409 without a verified-readback receipt, preserving the damaged evidence and the
other unchanged object. After an explicit external repair of the blob, the same
capture receives a verified duplicate receipt; the receiver does not repair or
replace files automatically.

A third test injects ENOSPC while flushing the temporary image file, before its
publication. It returns HTTP 503 without a receipt, removes its temporary file,
and leaves no committed image or capture record. A complete retry after removing
the fault succeeds once, then becomes an acknowledged duplicate. The injection
targets regular files, leaving POSIX directory synchronization intact.

All 109 image-archive tests pass, including 15 HTTP receiver tests. These are local
fault-injection checks; no device, user archive, NAS configuration or production
meter changed. They do not establish physical power-loss durability. Confirmed
receipts continue to leave images unreviewed and ineligible for training.


## Last-upload diagnostics — test-board deployment September 25

A camera-independent test on the ESP32 completed three saved-JPEG inference runs
with exact reference parity in 11.90–12.04 seconds while a synthetic archive item
was pending. No upload receipt arrived; two failures were counted. The receiver
had no committed capture record. The test restored disabled archiving, verified
unchanged configuration/profile and zero camera captures, and stopped its local
receiver. It did not establish successful inference/upload overlap or live
capture cadence. The transport failure's cause remains unresolved.

The status API previously exposed only a failure count. The deployed change adds
`last_http_status` (zero when unavailable), `last_attempt_ms` (completion time in
milliseconds since boot), and `last_upload_error` (a fixed internal code).
Unknown error text becomes `upload_failed`; credentials, destinations and response
bodies are never copied into this field. A verified success clears the last error
to `none`; historical failure counters remain. These fields describe the last
attempt, not every queued image or a wall-clock timestamp.

The archive page translates these codes into connection, credential, receipt or
saved-file guidance and shows **Retrying upload** for retained pending items.
Older firmware without the additional fields remains supported. Actual-worker,
queue, serializer and browser-state checks pass. The managed firmware build passed 91 host and 10 UI checks. OTA, boot, preserved
configuration/profile/password, new API fields and exact served-script bytes were
verified on the test board in bundle
`edda76191e325a8f616c17e9e05ccd5021f4e83b60bd06fbedfd61e0f8fd6096`.

Private evidence: `camera-free-archive-overlap-01/verification.json` under
firmware-port-tests. The image and metadata used for the upload were synthetic;
no production-meter request or NAS write was part of this trial.


The instrumented repeat reported `settings_connection_failed` with HTTP status
zero. The receiver recorded no TCP connection from the ESP32, although its TLS
listener passed a local check with the configured trust anchor. This narrows the
failure to establishing the connection; it does not prove a firewall, routing or
firmware root cause. Detailed Windows firewall inspection was denied. No firewall
rule was changed and the NAS was not contacted.

Three saved-JPEG runs still matched reference output exactly, taking
12.05–12.11 seconds. The maximum observed time for three sequential status requests
was 0.516 seconds. No upload was acknowledged, so successful concurrent delivery
and live capture cadence remain unverified. The actual served script maps the
recorded failure to **Retrying upload** and connection guidance. This is a script
check with recorded hardware status, not a rendered-browser check. Temporary
archive configuration and synthetic queue files were removed, disabled archiving
and unchanged configuration/profile were verified, and camera captures remained
zero. Private evidence: `camera-free-archive-overlap-02/verification.json` and
`served-ui-failure.json`; bundle evidence: `aiedge-archive-failure-diagnostics-01`.


## Test-board upload during inference — September 25

A bounded trial passed after adding a temporary Windows inbound rule restricted
to the test board and HTTPS receiver port. The board delivered a synthetic 32x32
JPEG and its settings descriptor, received a matching HTTP 201 acknowledgment,
and cleared the pending record. Receiver-side bytes and metadata matched exactly.
One deliberate HTTP 503 delayed delivery until inference began; automatic retry
then succeeded. The receiver observed image delivery while saved-JPEG inference
was active. All six dial features and outputs matched the reference, completing
in 12.272 seconds.

The test restored the original device configuration/profile, disabled archiving,
removed its temporary queue files and stopped the receiver. The temporary firewall
rule was removed and its absence checked. No production device or NAS was changed.
This supports a firewall cause for the prior failed local trials. It does not
establish full-size photo throughput, sustained 30-second live cadence, physical
camera capture, real-image accuracy, or NAS delivery from the ESP32. The synthetic
image and protected inference fixture remain excluded from training.

Private evidence: `camera-free-archive-overlap-03/{result,verification}.json` under
firmware-port-tests. Tested bundle: `b00984a26744f94e0a1ee6d65d1ec312bca44f49c6e07da33626d8953b0f3151`.
