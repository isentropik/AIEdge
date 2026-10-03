# App packaging (development)

The Home Assistant app directory is a complete Docker build context for Linux
amd64. It compiles separate recognition ABI 2 and accounting ABI 1 libraries,
installs hash-locked CPython 3.14 wheels, checks both model tensor contracts and
starts the app service. Capture is off by default. No meter-specific calibration
is activated on startup. Legacy replay geometry in the shared headers exists
only for explicit tests; it is not a default for other meters.

The dev20 draft passed Linux CI at commit
`401d2d6b942b37cd9414ad4710d9ab298800e58f`, including filesystem/process and
packaged startup/restart checks. [Verified run](https://github.com/isentropik/AIEdge/actions/runs/37109202136).
Dev21 adds the short trial; its exact draft must pass its own CI before release.
Neither CI nor a saved-image test proves actual camera behavior, sustained cadence
or population reading accuracy. Supervisor deployment and real-camera validation
are separate checks. Standalone Docker access/authentication remains pending;
the packaged default uses Home Assistant Ingress.

## Build and check

From the repository root on Linux amd64:

```sh
docker build --pull -t aiedge-app:development aiedge_app
node --test aiedge_app/test_*.cjs
docker run --rm --network none --mount type=bind,src="$PWD/aiedge_app",dst=/tests,readonly --entrypoint python aiedge-app:development /tests/run_validation.py --container --library /opt/aiedge/libaiedge_native.so --accounting-library /opt/aiedge/libaiedge_accounting.so --models /opt/aiedge/assets/models --allow-missing-archive-replay
```

The checked runner rejects unexpected skips and missing required tests. The
container check launches the packaged service, checks HTTP assets/API, restarts
it with the same data, preserves damaged configuration and tests Linux SIGTERM
draining. It also checks the packaged trial script and unavailable-camera status.
The CI workflow is `.github/workflows/aiedge-app.yml`.

`--allow-missing-archive-replay` permits seven explicit private archived-image/
profile checks. For authorized private replay, omit it and supply matching
`--archive-calibration`, `--archive-rgb` and `--archive-jpeg` files. Keep photos
and private calibration outside public source and CI artifacts. Generated scenes,
simulated transports and ledger trajectories are not real-image accuracy tests.
The JSON report lists each skip and whether packaged/private replay was required.

Windows host checks use the separately compiled native libraries and documented
fixture paths. Linux filesystem/process and packaged-service checks cannot be
inferred from Windows results. C++ interval checks use
`python aiedge_app/check_accounting_core.py` with a C++17 compiler; the Docker
native stage also runs them. They verify quantities, not needle recognition.

## Model and shared-header assets

Only `polar-main-float.tflite` and `polar-int8.tflite` are selected. The main model
uses dequantized frozen features; the secondary keeps its int8 contract. Pinned
hashes in `reader.py` must match the assets. Changing reader/model identity requires
an explicit number-format rebind and starts a separate consumption segment;
history retains the previous identities. The models are not independently
validated for arbitrary needle designs or lighting.

After changing shared Polar headers or models, regenerate from the repository root:

```sh
python aiedge_app/stage_assets.py --models PATH_TO_VERIFIED_MODELS
python aiedge_app/stage_assets.py --models PATH_TO_VERIFIED_MODELS --check
```

Do not edit `assets/include` directly. The snapshot retains upstream license and
attribution, with no photos or credentials. The image build verifies all 24 asset
hashes, loads both native libraries, invokes both pinned models and checks a
synthetic two-dial interval. The trial uses the existing guarded camera path;
see [trial instructions](CAPTURE-TRIAL.md).

## Base image and dependencies

Both stages pin `python:3.14.8-slim-trixie` to OCI index
`sha256:89fb7d3da20043c370643435258bdd7ab755d326d359001d02988ed15ae5219e`.
The selected Linux amd64 manifest is
`sha256:65a94bb37b630c482dfd31e5fb9b449cb26c31eab1b7a125cd6bd624acfe3b30`.
Official registry metadata inspected October 3, 2026 identifies Python 3.14.8
in its image configuration. A digest check does not prove startup or native
compatibility; the exact-head Linux build and packaged restart suite must pass
before release. Dependency locks and notices are documented in
`DEPENDENCIES.md`. Network-share archiving is optional and uses HA-managed mounts;
its real deployment and storage behavior require their own verified results.
