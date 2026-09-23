# Polar runtime equivalence test preparation

The parent workspace's `needle_reader_v2/export_polar_runtime_vectors.py` creates
`needle-training/firmware-port-tests/runtime-vectors/`. It verifies the frozen
model hash, compiles current C++ preprocessing, and extracts six accepted dial
tensors from one preserved real full-frame image. It runs each tensor through
TensorFlow Lite 2.16.1 reference and optimized desktop kernels. Their 360 output
bytes matched exactly for all six vectors in the September 22 run.

`polar-runtime-vectors.bin` contains `PLRTEST1` followed by six records, each with
15,360 signed-int8 input bytes and 360 signed-int8 expected output bytes. The
manifest records source image/model/input/output hashes and the output file hash.
Expected outputs are runtime reference results, **not human reading labels**.
The source is held-out trial evidence and remains excluded from training.

`PolarRuntimeTest.cpp` now implements the runner: it verifies the exact fixture
size/hash in the loaded workspace, acquires processing ownership, uses normal
model allocation/invocation, compares all output bytes and records per-dial
differences and inference timing. `InferPolarScores` shares `InvokePolar` with
normal recognition. Tensor tests cover invalid buffers and failed invocation
without changing caller output. The earlier incremental build did not discover
the new runner. After removing an ESP-IDF-incompatible CMake option, the September
22 clean build compiled `PolarRuntimeTest.cpp` and completed successfully in
183.11 seconds (53,248 bytes static RAM; 1,576,168 bytes flash). Candidate
packaging now requires a clean build to rediscover new source files. The runner is
wired to an explicitly requested asynchronous diagnostic. POST an empty request
to `/polar_runtime_test`; the existing basic-auth filter applies when configured.
It returns 202 when a worker is accepted, 409 if a diagnostic is already active,
400 for a body/query, or 503 if worker creation fails. GET the same path for the
result (no-store JSON). Acceptance is not completion. The worker rejects busy
processing rather than queuing behind a recognition cycle. It retains no HTTP
request and publishes its result only after completion. A new request clears
the previous result; results are volatile across restart. No automatic retries.
`test_polar_runtime_runner.py` exercises the actual runner with platform and
inference stubs: processing ownership, model/allocation/contract rejection,
workspace failure, missing/truncated/extra-byte fixtures, close/hash failures,
partial inference failure, byte mismatch counting, timing and lock release.
These tests passed; they do not validate ESP32 kernels or physical SD behavior.
`test_polar_runtime_http.py` checks the actual handler and worker bodies using
HTTP/FreeRTOS stubs: rejection, task failure, immediate response, duplicate
admission, cleared stale results, JSON and worker cleanup. Real scheduling,
authentication configuration and responsiveness still require device checks.
Only one six-vector job can run at once. The inference call itself is not
forcibly cancellable; hardware watchdog behavior remains to be validated.
Run it only as part of an approved live firmware trial. It does not capture an
image, publish a meter reading, train, or change configuration.
Byte differences require investigation; do not silently widen tolerance until
the device passes. One source frame is a runtime smoke test, not full angular
coverage, camera-path equivalence, sustained performance or empirical accuracy.

No diagnostic has run on the ESP32 and no firmware has been deployed.

After wiring the trigger, the ESP32 build passed (21.71 seconds; 53,360 bytes
static RAM and 1,578,868 bytes flash). The link map includes both handlers and
`runPolarRuntimeTest()`. These are build measurements, not device processing
times or peak runtime memory measurements. Packaging includes the diagnostic
fixture only after verifying its fixed length and SHA-256. On an approved trial,
its destination is `/sdcard/config/polar-runtime-vectors.bin`; placement has not
been performed. The existing archived development candidate predates this work.
