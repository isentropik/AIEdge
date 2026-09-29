# Dependency baseline

Reviewed September 28, 2026 against official Docker Python and PyPI package metadata.
Container base: python:3.14.7-slim-trixie, pinned to the verified OCI index digest
listed in PACKAGING.md on September 29.
Inference requirements pinned in requirements.txt: ai-edge-litert 2.2.0,
numpy 2.5.3, Pillow 12.3.0 and paho-mqtt 2.1.0. Installed into an isolated Python 3.12 Windows environment;
the older training environment was not modified. Current package metadata offers
CPython 3.14 wheels for the target Linux x86_64 runtime, but the container has not
been built or executed. Native C++ bridge built with the existing Zig C++ toolchain.

LiteRT reference-kernel parity verified against the old TensorFlow runtime on the
retained dense and sparse fixture. See STATUS.md for optimized-kernel differences.
JPEG replay is inference/compatibility evidence, not labeled accuracy validation.

Container packaging now includes both pinned models and builds the ABI-2 native
bridge from the shared-header asset snapshot. requirements-linux-amd64.lock pins
all resolved packages with wheel SHA-256 hashes for CPython 3.14 Linux amd64.
Those wheels were downloaded and the lock resolved again offline with hash checks.
This proves artifact availability, not Linux execution. The Windows packaged-header
build and model invocation smoke test pass; current host-suite results are recorded
in STATUS.md. Paho 2.1.0 is pinned with its wheel hash in the Linux lock and was
installed only into the isolated server environment.

Before release: build/test Linux Python 3.14 and Supervisor, inspect all dependency
licenses and scan dependencies. Debian compiler and
runtime package versions are not yet locked. No Docker or WSL runtime is installed
on the current Windows host. No container execution or HA installation is claimed.


Paho MQTT 2.1.0 was checked against official PyPI metadata on September 29.
A loopback MQTT 3.1.1 fixture exercised the real client handshake, QoS 1
acknowledgements, discovery/state publication and offline transition. This is not a
Mosquitto/Supervisor integration test.

Home Assistant app labels, optional MQTT service access and cold backups were checked
against the official app documentation:
- https://developers.home-assistant.io/docs/apps/configuration/
- https://developers.home-assistant.io/docs/apps/communication/
