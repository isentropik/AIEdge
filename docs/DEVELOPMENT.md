# Building AIEdge

Use a recursive checkout of the AIEdge release commit. The initial app uses upstream `a1ccda2` with modifications; retain pinned submodule revisions.

```sh
git clone --recursive https://github.com/isentropik/AIEdge.git
cd AIEdge
python -m pip install platformio==6.1.18
python -m platformio run --project-dir code --environment esp32cam-managed
python -m platformio run --project-dir bootstrap --environment esp32cam
```

The platform is Espressif 6.9.0 / ESP-IDF 5.3.1. Use a short Windows checkout path if toolchain path length causes problems. These commands build only.

The managed app requires its matching SD bundle. Bootstrap `package_pin.h` binds the exact release URL, ZIP size/hash, bundle ID and model identity. Regenerate pins and rebuild whenever the package changes. Do not use a mutable latest-release URL with fixed hashes.

## Package a changed app

`tools/aiedge/package_from_release.py` makes a development bundle from trusted release runtime assets plus a new app. It checks the seed hash, model identity and ESP32 image checksum. It does not validate recognition changes, update installer pins or deploy.

```sh
python tools/aiedge/package_from_release.py --seed aiedge-package.zip --seed-sha256 EXPECTED_SHA256 --firmware code/.pio/build/esp32cam-managed/firmware.bin --output my-development-package.zip
```

An old seed retains its old HTML. For web changes, regenerate assets and deliberately update their package inventory. Include model and diagnostics as well as firmware and HTML. Runtime vectors are consistency checks, not independent real-world accuracy labels.

## Validate

Compile both projects, check setup JavaScript and verify packages with the production stager. On hardware test AP, mDNS, scan/rescan/manual entry, bad passwords, interrupted downloads, certificate/SD failures, readback, first boot and recovery. Record source commit, tools and hashes.

The original local test harness depends partly on private labelled images and workspace tooling; it is not a complete public one-command suite. Public reproducible tests and broader hardware coverage remain work to do. Do not publish credentials, private images or complete board backups. Preserve upstream licensing and publish a new version rather than silently replacing release assets.
