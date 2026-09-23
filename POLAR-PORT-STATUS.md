# Polar meter reader port

Local development branch: `codex/polar-meter-reader`.
Base: upstream v16.1.0, `a1ccda2e88f8924d6633b285f7b3334f3263cc2f`.
No firmware has been flashed or published.

## Current integration status (September 22)

The opt-in PolarV1 flow now calls the ported preprocessing, visibility, frozen
model and atomic six-dial output path. Earlier standalone-port/build figures
below are historical, not the current binary's footprint or integration state.
The latest build/package manifest identifies the exact binary and source hashes.

Implemented locally and host-tested: interval accounting and cross-dial checks;
raw/provenance diagnostics; two-slot reference persistence with restart gaps;
shared controller processing exclusion; monotonic stage/capture timing and
missed-slot scheduling; RGBW channel encoding and master brightness; async
stream ownership and preview/save intensity; journaled intensity saves; and
generated configuration controls for PolarV1 and RGBW. These are implementation
and host-test results, not hardware validation.

Remaining major work includes cumulative consumption reconciliation across
uncertain gaps, full HTTP/MQTT freshness behavior, general safe configuration
reload, stream fairness and device responsiveness, ESP32 inference parity and
memory/cadence measurements, physical RGBW verification, browser verification of
the generated configuration page, and an exact approved installation/recovery
procedure. Frozen real-image validation remains limited; synthetic or unlabeled
results do not expand verified accuracy. The full objective remains incomplete.

## Updated performance target

User updated the objective to ideally capture every **30 seconds**. This supersedes
the older one-minute cadence target for new development. Measure complete valid
capture-to-publish cycles on the actual ESP32, including alignment, preprocessing,
inference, consistency/visibility checks and output publication. Use monotonic
stage timestamps and actual image-capture timestamps. Desktop parity test speed
is not device performance evidence. Never shorten the live interval as part of
local development. Require sustained cycles without overlap or queue growth,
record latency distribution and rejected/missed cycles, and measure web request
latency concurrently. If 30 seconds cannot be sustained, report measured limits
and bottlenecks instead of silently dropping checks or asserting success.

## Implemented, September 22

- Camera ownership is now shared by recognition capture, manual camera/light
  handlers and preview editing. Busy HTTP operations return 503; manual image
  export rejects failed captures instead of encoding stale pixels. Host ownership
  and failure fixtures pass with assertions explicitly enabled. Streaming now
  runs in one asynchronous worker and releases the camera before network sends.
  Temporary live intensity controls now apply at preview-frame boundaries and
  restore the recognition setting. Persistence, rendered UI and device
  timing/ownership validation remain unfinished. See
  `LIGHTING-PORT-STATUS.md`; no live deployment.

- Lighting software now has explicit four-byte GRBW SK6812 support, dedicated W
  configuration, external master-intensity scaling and GPIO built-in PWM routing.
  RGB modes retain three-byte output. Encoder/brightness and editor round-trip
  tests pass, and the ESP32 build succeeds. See `LIGHTING-PORT-STATUS.md` for exact
  scope and remaining live-slider, ownership, error-handling and physical checks.

- Portable `MeterAccounting.h` and Python `meter_interval.py` extend the existing
  main-register/cross-dial diagnostics with secondary-turn candidate bounds.
  Known 20/200-turn ratios, carries, jitter, backward totals, whole-register
  rollover/reset, sparse captures and explicit clock-domain checks are covered.
  2,500 randomized/reference comparisons pass. No arbitrary physical flow limit
  is supplied and ambiguous/noise intervals assert no consumption. This is not
  yet wired to live outputs or persisted across restarts. See `METER-ACCOUNTING.md`.
- The camera driver frame timestamp now travels with the RGB image into alignment.
  Capture/decode failures propagate through the normal flow and stop downstream
  publication with `Capture failed`, without retry/reboot for those failures.
  Buffer capacity and decoded dimensions are checked before copying. Eleven
  actual-function stub tests passed; controller tests now cover four cases.
  ESP32 build passed after these changes (35.36 seconds build time). Actual
  device capture timing and manual preview endpoint error handling remain to verify.

- Opt-in `[Analog] Reader = PolarV1` now connects the portable pipeline to the
  firmware flow. It checks the frozen model's loaded-byte SHA-256 and length,
  tensor contract, alignment settings, names/order/coordinates/directions of all
  six ROIs, and actual RGB frame dimensions. Invalid explicit selections and
  failed initialization cannot silently become a disabled-success flow. Default
  upstream selection is unchanged. `POLAR-CONFIGURATION.md` documents the local
  option and remaining live-trial prerequisites.
- The flow performs its own marker registration, frozen preprocessing, visibility
  rejection and typed inference. It commits readings only after all six pass;
  a failed frame invalidates all ROI results. Previews never feed inference.
  Scratch occupies the unused tail of the pre-reserved model region, not a new
  heap allocation, and cannot overlap the tensor arena. The polar translation
  unit has `-ffp-contract=off`, verified in generated compile commands.
- Host tests execute the actual new flow with real preprocessing and stubbed
  inference/device calls: 13 geometry/failure/success/stale-result cases passed.
  Actual typed tensor guards passed malformed type, dimension, length, pointer,
  quantization and Invoke failure fixtures. General flow tests now cover seven
  cases including polar initialization failure and polar branch selection.
  These do not verify TFLite Micro runtime inference or device accuracy.
- A clean ESP32 build including `ClassFlowCNNPolar.cpp` succeeded (186.86 seconds
  build time, not processing time): static RAM 51,920 bytes, flash 1,551,596 bytes.
  Final configuration-guard edits also passed an incremental build (32.26 seconds);
  artifact identity is recorded in `polar-integration-build.json` under the parent
  workspace's `needle-training/firmware-port-tests`. The
  earlier incremental linker failure was stale source discovery and was resolved
  by PlatformIO's clean target; no source files or device data were removed.

- Recognition failure propagation: `ClassFlowCNNGeneral::doFlow` now returns a
  model-load/allocation failure instead of unconditional success. The controller
  stops that cycle before post-processing/publication, publishes the status
  `Recognition failed`, and does not retry the same rejected recognition or
  enter the upstream reboot loop. Existing handling of other stage failures is
  unchanged. Tests compile the actual function bodies with dependency stubs:
  four stage-result cases and three controller cases pass. Evidence is in
  `flow-failure-results.json` and `controller-failure-results.json` under the
  parent workspace's `needle-training/firmware-port-tests`. This is not yet a
  complete stale-output policy: existing stored/retained values remain available,
  manual single-stage endpoints still need review, and upstream float inference
  does not yet check Invoke failures. The new polar Invoke path does check them.
- `HasPolarTensorContract` exposes the existing strict tensor checks without
  running inference, for the forthcoming opt-in flow initialization. It validates
  tensor layout/quantization, not artifact identity; frozen model hash validation
  remains required at integration.

- `PolarVisibility.h` adds the frozen contrast and interior-needle visibility rejection before feature extraction. Combined pipeline tests now cover 108 dial crops (90 trial crops plus 18 crops across three obscuration fixtures): zero differing accepted feature bytes, visibility scores within 1e-8, all three covered secondary needles rejected. Rejected buffers are not valid inference inputs. These are regression fixtures, not new accuracy labels or universal obstruction detection.

- `PolarPipeline.h` and generated `PolarCalibration.h` combine fixed marker geometry, registration, direct RGB ROI warp, grayscale, blur, polar sampling and quantization. `test_firmware_pipeline.py` compares all six dials from all 15 saved frames: **90 crops, zero differing feature bytes** (1,382,400 int8 bytes). Python only supplies decoded source RGB and the reference outputs. C++ performs its own registration and coordinate generation. Model inference, JPEG decoding, visibility checks and live flow integration remain outside this test. Evidence: `needle-training/firmware-port-tests/pipeline-results.json`.
- Geometry export validates frozen artifact hashes before generating constants; preserves the fixed needle pivot and original perspective homographies. `export_firmware_geometry.py` writes source hashes and generated-header hash to `geometry-export.json`.

- `PolarDecoder.h`: int8 probability centroid, circular peak window, CW/CCW conversion and invalid-input rejection.
- `PolarFeatures.h`: calibrated coordinate sampling, per-radius percentile normalization, circular padding and int8 quantization. Caller-provided scratch memory avoids large stack allocations.
- `PolarImage.h`: RGB luma conversion and fixed-radius blur. Host comparison against Pillow passes all pixels in 25 cases (15 trial frames plus random, constant and degenerate-size fixtures).
- `PolarAlignment.h`: normalized marker matching, subpixel offsets and rigid registration. Matches Python on 15 real frames and two constructed valid translations (matrix difference below 2e-13); rejects boundary matches, changed marker spacing, obscured images and flat templates. Pixel warp is still pending.
- `PolarWarp.h`: bicubic RGB ROI sampling, avoiding a second full RGB image allocation. All pixels match Pillow in twelve real dial crops and four constructed affine/boundary cases. Tests: `needle_reader_v2/test_firmware_warp.py`, evidence `needle-training/firmware-port-tests/warp-results.json`. This supersedes the pending-warp note above; combined full pipeline and on-device checks remain pending.
- `CTfLiteClass::InferPolar`: separate typed entry point checking tensor dimensions, byte lengths, quantization and Invoke status. Existing RGB/float callers remain unchanged. This method has not yet been compiled against the full ESP-IDF build.

Host tests in the parent workspace:

- `needle_reader_v2/test_firmware_decoder.py`: 1,181 constructed distributions; maximum circular Python/C++ difference 0.0000004623. Invalid pointers/count and zero probability mass rejected.
- `needle_reader_v2/test_firmware_features.py`: twelve real crops from two held-out trial frames, covering all six dials. All 184,320 quantized feature bytes match Python exactly. Images remain evaluation-only.
- Evidence: `needle-training/firmware-port-tests/decoder-results.json` and `features-results.json`.
- Alignment evidence: `needle-training/firmware-port-tests/alignment-results.json`; test command `needle_reader_v2/test_firmware_alignment.py`.

Build tools: PlatformIO 6.1.18 belongs in parent `.venv-firmware`, isolated from
HA tooling. An initial install into `.venv-ha` downgraded three packages; it was
removed and original starlette 1.6.0, uvicorn 0.52.4 and click 8.5.0 restored.
HA `pip check` passed after restoration. The initial PlatformIO dependency
installation repeatedly failed extracting a deeply nested ESP-IDF file under
the long workspace path; that process was stopped. A reversible `subst P:`
alias points to the workspace (no files moved). The current build uses
`PLATFORMIO_CORE_DIR=P:/.pio-core` and project
`P:/firmware/AI-on-the-edge-device/code`, via `.venv-firmware`. Remove this
session-created alias with `subst P: /D` only after all build processes finish.
Short-path SDK installation succeeded. The first configure then failed because
Git searched upward from the packaged SDK into the enclosing workspace. The
build retry sets `GIT_CEILING_DIRECTORIES` to both alias and canonical `.pio-core`
paths, preserving package `version.txt` provenance without inventing Git commits.
Complete current build output is `needle-training/firmware-port-tests/esp32-build.log`.
This build succeeded: RAM static usage 51,912/327,680 bytes; flash
1,524,768/1,945,600 bytes. It verifies the added CTfLiteClass entry point compiles
against the pinned ESP-IDF/TFLite Micro. The portable pipeline headers are not
yet called from the firmware flow, so this is NOT a complete polar-reader build
or a runtime/memory/performance validation of the pipeline. No firmware uploaded.

These tests establish host algorithm parity only. The feature test supplies Python-aligned RGB images and calibration coordinates, then performs grayscale, blur and features in C++. It does not test firmware image alignment, JPEG decoding, TFLite Micro execution or physical meter accuracy.

Blur parity reference: Pillow 12.3.0 `src/libImaging/BoxBlur.c`, https://github.com/python-pillow/Pillow/blob/12.3.0/src/libImaging/BoxBlur.c . The fixed-radius implementation uses three fractional box passes per axis, replicated edges and per-pass uint8 rounding. It is not a general Gaussian blur API.

## Still required

1. Verify the ported fixed geometry and marker registration on device; host full-frame parity is covered. Preserve distinct printed-dial and needle pivots.
2. Validate the connected opt-in analog flow end-to-end on device, finish configuration UI preservation and manual-stage handling, and restore logging semantics. Host integration and compilation are not runtime validation.
3. Verify the pinned TFLite Micro operator versions, allocation, actual ESP32 output parity, memory and valid-cycle performance. The flatbuffer uses RESHAPE, CONV_2D, ADD and SOFTMAX, all registered upstream, but operator names alone do not prove compatibility.
4. Port visibility rejection and cross-dial diagnostics; resolve the recurring last-pair discrepancy using evidence without retraining on held-out trial frames.
5. Implement bounded secondary-wheel consumption/flow, missing-turn ambiguity and restart continuity using real capture timestamps.
6. Complete the RGBW white-channel, external LED intensity, responsiveness and safe configuration-activation requirements from `needle-training/FIRMWARE-FORK-BACKLOG.md` in the parent workspace.
7. Build firmware and web assets reproducibly, document rollback and exact changes, obtain live deployment approval, then validate on-device readings, MQTT/HA behavior, timing and recovery.

The replacement goal remains incomplete. No new empirical accuracy is claimed from unlabeled trial images or constructed tests.
