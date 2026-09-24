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

The additional UI counters are prepared in source; device deployment and rendered
verification remain pending. Earlier successful HTTPS delivery does not establish
these failure scenarios on hardware.
