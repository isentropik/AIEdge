# App packaging (development)

The Home Assistant app directory is a complete Docker build context. The container
compiles separate native recognition and accounting libraries, installs hash-locked CPython 3.14 Linux
amd64 wheels, verifies both models and starts the calibration/recognition service.
Capture is off by default. No meter-specific calibration is activated on startup.
The shared headers still contain the explicit legacy replay calibration; it is not
a generic calibration for other meters. These models are not independently verified
for arbitrary needle designs or lighting.

Maintainers: after changing shared Polar headers or the pinned models, refresh the
asset snapshot from the repository root:

```
python aiedge_app/stage_assets.py --models PATH_TO_VERIFIED_MODELS
python aiedge_app/stage_assets.py --models PATH_TO_VERIFIED_MODELS --check
```

Model SHA-256 values must match reader.py. The snapshot retains upstream attribution
and license. It contains no capture archives, Wi-Fi passwords or device credentials.
Do not edit assets/include directly; update the shared firmware source and regenerate.

On a Linux amd64 Docker host, build from the repository root:

```
docker build -t aiedge-app:development aiedge_app
```

The image build checks all 24 packaged-file hashes, loads recognition ABI 2 and
accounting ABI 1, verifies tensor shapes and quantization, invokes both models, and
checks a synthetic two-dial interval. Accounting remains separate from recognition. The changed-dial cache is an additive
ABI 2 entry point; it preserves the full path for changed or rejected regions. Its new
recognition binary and reader source produce a new pipeline identity. Existing dial
values must be reviewed and rebound to that identity before readings are enabled.
These checks do not prove recognition accuracy.
The default command requires HA Ingress; direct network access is intentionally
rejected. Standalone remote authentication and a standalone Docker launch workflow
remain pending. The dev5 development container built and started on one Home Assistant Linux amd64 host
on September 30. UI/API checks and an approved saved-image calibration/persistence
test pass. The actual container accepted all six dials and retained the reference hash,
calibration and ft³ format after an app restart, with capture/MQTT disabled. The full
Linux regression suite has not run. A first experimental HA test
can build it through the app store using the branch-specific repository URL in
DOCS.md, with capture and MQTT disabled. This is not a validated release or a
replacement for the existing meter. MQTT is implemented locally; its Supervisor
integration and the camera firmware still need end-to-end validation. External archives are deferred; images
stay in app storage. Windows packaged-header compilation and the local app suite
pass. A Linux Docker build and packaged-service startup workflow is prepared locally in
`.github/workflows/aiedge-app.yml`; it is not published. A successful full run is still required for Linux regression coverage.


The September 29 attempt to push the CI workflow was rejected by GitHub because the
current OAuth connection lacks workflow permission. No Linux CI run occurred. The
workflow remains prepared locally; do not treat its presence as a successful build.

## Base image pin

Both stages use `python:3.14.7-slim-trixie` at OCI index digest
`sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d`.
The official registry's Linux amd64 manifest is
`sha256:7bf6c3111fe094f8ee1a1cbcdc63c4cfb345b0e3df42d5aa9a90b3b4b022ab6d`.
The manifest and configuration hashes, platform and Python version were checked on
September 29, 2026. This pins the selected base; it is not evidence of a successful
Linux build or Supervisor run. Update the digest deliberately when taking base-image
security updates, then repeat the container build and service checks.

## Local regression checks

From the repository root, use the project's Python environment and Node.js:

```
python -m unittest discover -s aiedge_app -p "test_*.py"
node --test aiedge_app/test_editor_geometry.cjs aiedge_app/test_reference_image.cjs aiedge_app/test_dashboard.cjs
```

Native/model fixture checks require the paths documented in their test modules.
Set `AIEDGE_ACCOUNTING_LIBRARY` to the separately compiled accounting library to
run the durable consumption regressions. The shared C++ interval-oracle checks are
run with `python aiedge_app/check_accounting_core.py` using an existing C++17
compiler. Windows development can use `--zig-python PATH_TO_PYTHON_WITH_ZIG`.
The Docker build runs these checks in its native build stage. They cover synthetic quantities, not model accuracy.
A run with skipped fixtures does not establish native recognition compatibility.
The Linux-only packaged-runtime check needs `AIEDGE_CONTAINER_TEST=1` inside the
built container; it is intentionally skipped on the Windows development host.

## Required native coverage

Use the checked runner instead of interpreting a green test command with skipped
native fixtures as a complete result:

```
python aiedge_app/run_validation.py --library PATH_TO_RECOGNITION_LIBRARY --accounting-library PATH_TO_ACCOUNTING_LIBRARY --models PATH_TO_MODELS --allow-missing-archive-replay --report validation.json
```

It loads both native ABIs and both pinned models, requires the durable-accounting,
number-format and generated-image checks, and rejects unexpected skipped tests or
missing test files. The generated scene exercises both needle-model routes and
stationary capture persistence. It is synthetic coverage, not reading accuracy.

For the packaged Linux amd64 service, mount the source tests read-only and require
its startup/restart check:

```
docker run --rm --network none --mount type=bind,src="$PWD/aiedge_app",dst=/tests,readonly --entrypoint python aiedge-app:development /tests/run_validation.py --container --library /opt/aiedge/libaiedge_native.so --accounting-library /opt/aiedge/libaiedge_accounting.so --models /opt/aiedge/assets/models --allow-missing-archive-replay
```

`--allow-missing-archive-replay` explicitly permits six archived-image/profile checks
to remain unrun. It does not turn generated images into real-image validation.
For authorized private replay, omit that flag and supply `--archive-calibration`,
`--archive-rgb` and `--archive-jpeg` together. Those files must match the frozen
replay profile. Keep photographs and private calibration fixtures outside public
source and CI artifacts. The JSON report lists every skipped check and identifies
whether archive replay and packaged startup were required.

The prepared workflow now uses this runner and the accounting library. It remains
unpublished because workflow permission is unavailable. Neither the runner's
Windows results nor the workflow file establishes Linux or Supervisor execution.
