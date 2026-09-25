# Model reload memory ownership

The loader now destroys its interpreter before changing model bytes, clears
cached tensors, and registers its operator resolver once with checked results.
Reloads reuse the existing model allocation. A second network cannot take a
shared region already owned by another network, and failed construction cannot
release memory owned by image capture or another inference instance. Copying a
network owner is disabled.

A host test compiles the actual loader and shared allocator methods with a
tracked interpreter stub. It covers reload destruction order, pointer clearing,
missing files, failed allocation and retry, resolver failure, equal-size reload
workspace-tail preservation, absent memory, rejected second ownership and
capture-stage ownership. Run with Python and the ziglang package installed:

```
python tools/bundle-tests/test_model_reload.py
```

Validation: 87 host scripts, nine UI scripts and a clean ESP32 managed build
passed. Test-board OTA boot verification preserved configuration, meter profile
and authentication. One six-dial saved-JPEG replay took **11.691311 seconds** and
matched every expected preprocessing and output byte. No camera cycle ran.

Test bundle: `2be8e759f4275bfe7fe9ca9507111166655f5adadd2263035ad3f137e1bbd685`.
Package SHA256: `979eec34755c741930f44fbf6f06e1a57a11d2e51eefacd4e4cb4d93d98afb7b`.
The previous immutable bundle remains the rollback target:
`cdd03e4a92bdeef837144695555343af3d6b69769e216eecf39c72b5d1b924f3`.
Local evidence: `needle-training/firmware-port-tests/aiedge-model-reload-01/`
contains build/test logs, source hashes, OTA backup/readback and replay results.

The firmware still uses the original frozen model and calibration. The improved
main-dial candidate and role switching are not deployed. The replay establishes
no regression on this fixture; it does not test switching between different
models on hardware, live capture cadence, or independently labeled accuracy.
The test board reports camera initialization error 0x105, so live-camera evidence
remains unavailable. The production meter was not modified.
