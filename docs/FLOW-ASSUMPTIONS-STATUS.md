# Optional maximum flow setting

Local implementation in progress; not connected to firmware or deployed.

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
uncertain outgoing save. It is not yet wired into `PolarAccounting`.

Still required: revision-checked authenticated API,
processing-owner activation wiring at a safe cycle boundary,
history enumeration and assumption labels,
UI explaining ambiguity and the risk of an incorrect upper bound, firmware integration
tests for switching bounds and restoring previous namespaces, then test-board
build and readback. Naming alone does not implement runtime isolation.

Keep production unchanged. Do not infer turns from retrieval timestamps or use
this setting to conceal contradictory main-dial readings. Unlabeled readings
and successful replay tests do not establish real-image accuracy.
