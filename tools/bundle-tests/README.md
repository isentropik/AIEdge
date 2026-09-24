# Bundle recovery regression tests

These tests run firmware C++ code on your computer. They do not contact a device,
flash firmware, use meter photographs, or read your device configuration.
All test bundles contain synthetic bytes and use temporary folders.

## Run the complete bundle suite

Use Python 3 and the ESP-IDF framework used for the firmware build. The verified
Windows run used the Python `ziglang` package version 0.14.1. Install it in your
development virtual environment:

```sh
python -m pip install ziglang==0.14.1
python tools/bundle-tests/test_bundle_recovery.py --idf /path/to/framework-espidf
```

The SDK path must contain `components/mbedtls/mbedtls` and
`components/json/cJSON`. Alternatively, set `IDF_PATH` to that framework root.
The runner compiles the repository's actual headers, miniz, SDK cJSON and SHA-256
implementation. It does not download dependencies or substitute a mock hash.
Run without Python's `-O` option; assertions are required. C++ assertions stay
enabled even in the optimized host build.

A passing run prints:

- 28 streamed bundle verification cases
- 19 application-keyed boot selection cases
- 14 installation-index publication cases
- 8 managed transaction cases
- 13 actual miniz staging cases

The complete suite passed against the current public source on Windows. A separate
temporary source copy using the pre-fix installation-index header failed exactly
at retry after a simulated sync failure, confirming that the regression test
detects the repaired bug. The active worktree and test device were unchanged by
that comparison.

Index cases include retry after failed synchronization, incomplete or conflicting
pending bytes, exhausted preservation slots, and immutable completed mappings.
Staging cases include truncation, unsafe paths, changed bytes, failed sync and
preserving interrupted files on retry. Each verification case checks that
read-only verification did not modify its fixture.

The flash writer is simulated: these tests check whether valid transactions
request boot selection and invalid transactions refuse it. They do not establish
physical flash or SD power-loss durability. Run the hardware recovery checks
separately before making those claims. Windows is verified; the POSIX filesystem
branch is included but has not yet been exercised in this project.

## Staging-directory preservation alone

```sh
python tools/bundle-tests/test_pending_recovery.py
```

This smaller test covers the 32-slot preservation bound and filesystem conflicts
without requiring the SDK. Both runners compile into temporary directories.


## Automatic capture scheduling

With the same Python/ziglang setup, run:

```sh
python tools/bundle-tests/test_cycle_schedule.py
```

This extracts the actual controller's busy-round guard and end-of-round delay
block, compiles them with a deterministic clock/RTOS substitute, and compares
10,015 schedule calculations with an integer reference. Eight controller checks
cover busy-round counting, later missed slots, deadline boundaries and invalid
intervals. It needs no ESP-IDF path, device or private image fixtures. Passing does
not establish hardware scheduling latency or a sustained capture cadence.
