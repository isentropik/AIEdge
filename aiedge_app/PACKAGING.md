# App packaging (development)

The Home Assistant app directory is a complete Docker build context. The container
compiles the native recognition library, installs hash-locked CPython 3.14 Linux
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

The image build checks packaged-file hashes, loads ABI 2, verifies tensor shapes and
quantization, and invokes both models. It does not prove recognition accuracy.
The default command requires HA Ingress; direct network access is intentionally
rejected. Standalone remote authentication and a standalone Docker launch workflow
remain pending. Do not install this development build on live HA yet: Linux and
Supervisor execution have not been tested. MQTT is implemented locally; its Supervisor
integration and the camera firmware still need end-to-end validation. External archives are deferred; images
stay in app storage. Windows packaged-header compilation and the local app suite
pass. A Linux Docker build and packaged-service startup workflow is prepared locally in
`.github/workflows/aiedge-app.yml`; it is not published. A successful run is required
before treating this as Linux-compatible.


The September 29 attempt to push the CI workflow was rejected by GitHub because the
current OAuth connection lacks workflow permission. No Linux CI run occurred. The
workflow remains prepared locally; do not treat its presence as a successful build.
