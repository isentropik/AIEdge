# Building AIEdge

**This guide is for developers changing the software.** You do not need these steps to install a release. For that, use the [beginner installation guide](INSTALLATION.md).

A recursive checkout downloads this repository and its pinned dependency repositories (Git submodules). PlatformIO downloads and runs the tools needed to compile the code into firmware.

Use a recursive checkout of the AIEdge release commit. The initial app uses upstream `a1ccda2` with modifications; retain pinned submodule revisions.

```sh
git clone --recursive --branch v0.1.1-dev.20260922 https://github.com/isentropik/AIEdge.git
cd AIEdge
python -m pip install platformio==6.1.18
python -m platformio run --project-dir code --environment esp32cam-managed
python -m platformio run --project-dir bootstrap --environment esp32cam
```

The platform is Espressif 6.9.0 / ESP-IDF 5.3.1. Use a short Windows checkout path if toolchain path length causes problems. These commands build only.

The example checks out the USB Wi-Fi release tag. To work on another release, substitute that tag deliberately. To develop new changes from a release, create a branch before editing. Upstream publishing workflows have been removed from the AIEdge development branch; this guide does not promise a ready-to-run GitHub build service.

The managed app requires its matching SD bundle. Bootstrap `package_pin.h` binds the exact release URL, ZIP size/hash, bundle ID and model identity. Regenerate pins and rebuild whenever the package changes. Do not use a mutable latest-release URL with fixed hashes.

## Package a changed app

`tools/aiedge/package_from_release.py` makes a development bundle from trusted release runtime assets plus a new app. It checks the seed hash, model identity and ESP32 image checksum. It does not validate recognition changes, update installer pins or deploy.

```sh
python tools/aiedge/package_from_release.py --seed aiedge-package.zip --seed-sha256 EXPECTED_SHA256 --firmware code/.pio/build/esp32cam-managed/firmware.bin --output my-development-package.zip
```

An old seed retains its old HTML. For web changes, regenerate assets and deliberately update their package inventory. Include both required models, firmware and HTML. Runtime vectors are optional development consistency checks, not independent real-world accuracy labels.

## Validate

Compile both projects, check setup JavaScript and verify packages with the production stager. On hardware test AP, mDNS, scan/rescan/manual entry, bad passwords, interrupted downloads, certificate/SD failures, readback, first boot and recovery. Record source commit, tools and hashes.

The original local test harness depends partly on private labelled images and workspace tooling; it is not a complete public one-command suite. Public reproducible tests and broader hardware coverage remain work to do. Do not publish credentials, private images or complete board backups. Preserve upstream licensing and publish a new version rather than silently replacing release assets.


## Packages without private replay images

Add `--without-diagnostics` to `package_from_release.py` to exclude every asset
under `diagnostics/`, including replay photos and feature/output vectors. Firmware,
HTML, both models and their hashes are retained. The tool rebuilds the manifest
and bundle identity; it never edits the source ZIP. Configuration and validation
folders are not copied. Review the retained HTML, models and documentation before
publication; this option is not a general secret scanner.

The updated application accepts a bundle without diagnostic fixtures. Older
applications may require them: install a compatible transitional application with
its existing diagnostics first, then install the package without diagnostics using a distinct application build.
The packager rejects reusing the seed application for the diagnostic-free update;
application-to-bundle mappings remain immutable.
Do not publish or flash an untested stripped package just because packaging passed.
The raw/RGB/JPEG diagnostic endpoints will lack their fixtures; this does not
provide a new accuracy result. Normal recognition still requires both compiled
model identities, the configured camera geometry and the matching calibration.

Run `python tools/aiedge/test_package_from_release.py` for six synthetic package
checks. No real meter pictures or credentials are used by those tests.


## Export the tested runtime for release review

Once a diagnostic-free development package has passed device checks, export its
runtime without rebuilding or changing its bundle identity:

```sh
python tools/aiedge/export_runtime_package.py --seed tested-development.zip --seed-sha256 EXPECTED_SHA256 --output release-review.zip
python tools/aiedge/test_export_runtime_package.py
```

The exporter verifies the firmware digest, every runtime asset, and the complete
manifest. It copies only firmware, declared HTML/model assets, the unchanged
manifest and `docs/Licence.md`. Local validation reports, source inventories,
configuration and development README files are omitted. It refuses diagnostic
assets, duplicate ZIP entries, invalid asset paths, changed runtime bytes and
existing output files. Eight offline synthetic cases cover these boundaries.

The resulting ZIP has a new archive hash but the same bundle ID as the tested
runtime. It is not a new device update and cannot fix bugs in that runtime.
Review retained content (including firmware, HTML and models) for private data,
licensing and suitability before publishing. Export does not upload anything,
update the installer pin, or establish accuracy for other meters.
