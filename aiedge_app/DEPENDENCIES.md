# Dependency baseline

Official PyPI metadata checked October 3, 2026: all eleven Linux lock pins
are the latest stable releases with compatible CPython 3.14 Linux amd64
wheels. Exact wheel hashes and Python version requirements were verified.
The newer backports.strenum 1.3.1 requires Python below 3.11; keep compatible
1.2.8. Matching metadata is availability evidence, not runtime proof.

Container base: Python 3.14.8 slim trixie, pinned to the official OCI index
and Linux amd64 manifest in PACKAGING.md. The official Python release page
lists this patch release on September 30. Debian packages and bundled native
libraries are not covered by this registry audit.

Inference requirements pinned in requirements.txt: ai-edge-litert 2.2.0,
numpy 2.5.3, Pillow 12.3.0 and paho-mqtt 2.1.0. Installed into an isolated Python 3.12 Windows environment;
the older training environment was not modified. The dev5 container built and
started on one Home Assistant Linux amd64 host on September 30. Saved-reference,
six-dial calibration and number-format persistence passed after an app restart,
with capture and MQTT disabled. Native C++ bridges also built with the existing
Zig C++ toolchain.

LiteRT reference-kernel parity verified against the old TensorFlow runtime on the
retained dense and sparse fixture. See STATUS.md for optimized-kernel differences.
JPEG replay is inference/compatibility evidence, not labeled accuracy validation.

Container packaging now includes both pinned models and builds the ABI-2 native
bridge from the shared-header asset snapshot. requirements-linux-amd64.lock pins
all resolved packages with wheel SHA-256 hashes for CPython 3.14 Linux amd64.
Those wheels were downloaded and the lock resolved again offline with hash checks.
The lock check proves artifact availability; the separately verified dev5 startup
provides limited Linux runtime evidence. The Windows packaged-header
build and model invocation smoke test pass; current host-suite results are recorded
in STATUS.md. Paho 2.1.0 is pinned with its wheel hash in the Linux lock and was
installed only into the isolated server environment.

Before release: complete the Linux regression suite and capture/MQTT integration
checks, inspect all dependency licenses and scan dependencies. Debian compiler
and runtime package versions are not yet locked. No Docker or WSL runtime is
installed on the current Windows host. The September 30 local run passed 213
tests with native models and private archive replay; its one skipped check is
the Linux-only packaged-service startup/restart test. This is Windows coverage,
not the complete Linux suite or a verified live camera workflow.

Direct-pin metadata sources:
- https://pypi.org/pypi/ai-edge-litert/json
- https://pypi.org/pypi/numpy/json
- https://pypi.org/pypi/Pillow/json
- https://pypi.org/pypi/paho-mqtt/json


Paho MQTT 2.1.0 was checked against official PyPI metadata on September 29.
A loopback MQTT 3.1.1 fixture exercised the real client handshake, QoS 1
acknowledgements, discovery/state publication and offline transition. This is not a
Mosquitto/Supervisor integration test.

Home Assistant app labels, optional MQTT service access and cold backups were checked
against the official app documentation:
- https://developers.home-assistant.io/docs/apps/configuration/
- https://developers.home-assistant.io/docs/apps/communication/

## September 29 notice and advisory check

The exact eleven Linux wheels now have a retained notice inventory in
[third-party/manifest.json](third-party/manifest.json). Original texts are kept
verbatim with SHA-256 hashes and source paths. LiteRT and FlatBuffers did not
include separately named license files; matching-release upstream texts were
retrieved from their official repositories. The container build verifies the
inventory against the Linux lock and includes it in `/opt/aiedge/third-party`.

An OSV package/version query on September 29 returned no matching advisories for
these eleven pinned Python package versions. This is a limited database lookup,
not a clean bill of health: bundled native libraries and Debian packages were
not covered. Full binary notices and container vulnerability review remain open.

Sources:
- https://github.com/google-ai-edge/LiteRT/blob/v2.2.0/LICENSE
- https://github.com/google/flatbuffers/blob/v25.12.19/LICENSE
- https://osv.dev/

October 3 sources:
- https://www.python.org/downloads/release/python-3148/
- https://hub.docker.com/_/python
- https://pypi.org/pypi/backports.strenum/json
