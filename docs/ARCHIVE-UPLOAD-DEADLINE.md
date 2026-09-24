# Archive upload timeout

Settings metadata and the image share one configured network timeout budget.
Previously each request started a fresh budget: two requests taking ten seconds
each could succeed with a fifteen-second setting. They now time out within the
shared network budget, subject to the underlying network operation honoring its
remaining timeout. Local SD verification, cleanup and task scheduling are outside
this network budget; this is not a hard real-time bound on the whole worker.

A failed upload retains its verified local spool record. A subsequent successful
retry must receive a matching acknowledgment before queue cleanup. Capture does
not wait for network work; while the worker reserves admission during an upload,
new archive handoffs can be rejected and counted. This is best-effort archival,
not a promise to preserve every capture during a storage outage.

Validation: the actual C++ uploader with real spool files and SHA-256 passed the
existing 28 settings/image transport outcomes plus a shared-budget regression.
The regression failed before the change; it simulates two ten-second connection
operations, verifies timeout and retained spool data, then verifies a successful
retry. Worker admission/memory and capture binding regressions also passed.
HTTP and clock boundaries are simulated; this does not establish LAN timing or
TLS/inference memory headroom on hardware.
