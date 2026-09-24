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
