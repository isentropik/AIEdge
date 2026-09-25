# Optional maximum flow setting

Installed and verified on the test board on September 24, 2026. Production and the public installer are unchanged.

`MeterAssumptions.h` accepts a strict version-1 JSON document with
`maximum_flow_ft3_hour`: null disables the bound; a positive finite number
sets it. Default remains disabled. No household rate has been selected.
The bound converts to cubic feet per second, preserving the existing 0.1-dial
uncertainty assumptions. It is a physical upper bound, not measured flow.

Enabled checkpoint names encode the effective IEEE-754 rate; disabled uses the
existing checkpoint prefix. Parsing and name generation leave outputs unchanged
on rejection. Host tests passed with the existing cJSON library and Zig compiler:

```
.venv-ha/Scripts/python.exe firmware/AIEdge-publication/tools/bundle-tests/test_meter_assumptions.py --idf P:/.pio-core/packages/framework-espidf
```

Journaled storage is now implemented in `MeterAssumptionsStore.h`. Host tests
cover first saves, changes, disabling, stale revisions, torn journals, torn
settings writes, recovery after interruption, third-revision conflicts, cleanup
failures and read failures. Read-only inspection never performs recovery and
never interprets corrupt settings as the disabled default. These are host
fault-injection tests, not physical power-cut tests.

`MeterAssumptionsRuntime.h` now coordinates separate session/recovery objects.
Host tests verify idempotent activation, switching enabled/disabled bounds,
restoring an earlier namespace with an explicit gap, retaining the prior segment,
and keeping the current session intact after corrupt target history or an
uncertain outgoing save. `PolarAccounting` now uses `MeterAccountingController` to restore settings once,
apply them before observations, publish actual persistence status and refuse
accounting when configuration recovery fails. History reads select the active
namespace. Controller tests cover missing settings, configured limits, restart
gaps, damaged settings, no blind retry, and explicit recovery activation.

The authenticated `/meter_assumptions` GET/POST endpoint is implemented with
strict bodies, revision hashes, processing/storage guards, verified saves and
separate saved/active status. GET is read-only. The form on Meter and units
leaves the limit disabled by default and never retries a save automatically.
HTTP host tests and both form tests pass. History scan results are invalidated
on saves, including scans that finish after a setting changes.

Test-board bundle:
`4b98fa31bf27aa1168df6ff58963172ae49c686a84b2098946ed68e9ec2d217a`.
All 86 host checks, nine UI checks and the ESP32 build passed. Managed OTA,
verified boot and configuration/profile/password preservation passed. The live
endpoint rejected unauthenticated, invalid and stale requests; saving the disabled
default reported saved-and-active and read back correctly. Served HTML/JS matched
source bytes, including correct UTF-8 symbols. A saved JPEG completed in
11.817055 seconds with six tensors and six output arrays matching exactly.
Automatic captures stayed at zero and image archiving remained disabled.

Still open: rendered mobile layout verification, nonzero-bound transitions on
physical hardware, and validation against real captured consumption sequences.
Host tests cover nonzero limits and history isolation; no household maximum rate
has been selected. Replay parity is not independent accuracy or capture cadence.
Private evidence: `aiedge-flow-assumptions-05/{ota,runtime-verification,saved-jpeg-smoke,RESTORE.md}`
under `needle-training/firmware-port-tests`. Earlier candidates preserve failed
host-harness/compile checks and the superseded text-encoding issue.

Keep production unchanged. Do not infer turns from retrieval timestamps or use
this setting to conceal contradictory main-dial readings. Unlabeled readings
and successful replay tests do not establish real-image accuracy.
