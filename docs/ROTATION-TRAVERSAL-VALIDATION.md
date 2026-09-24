# Row-order image transforms

Rotation, antialiased rotation and translation now visit output pixels by row
instead of column. Coordinate calculations, interpolation, boundary fill and
resolution are unchanged. This keeps neighboring writes together in PSRAM.

The portable test under `tools/camera-tests/test_rotation.py` compares production
functions with the preserved original implementation. All 480 cases passed with
every output byte and resulting geometry identical. Coverage includes full-size
RGB frames, grayscale, flips, multiple angles and both scratch allocation paths.
The ESP32 build passed.

Managed OTA installed and verified test-board bundle
`58e442c75990fe2b31e16fabde18f86482dc883b52da3574c481e09ee504502f`.
Settings, meter profile and website authentication were preserved.

At 160 MHz with the same normal-camera trial configuration, the alignment stage
measured **1.874827 seconds**, compared with **3.919806 seconds** in the preceding
camera-copy trial. This is one before/after observation, not a sustained timing
distribution. The stage includes more than the rotation operation. Capture took
4.901396 seconds; polar registration took 2.093045 seconds before rejecting the
non-meter scene. No accepted readings or 30-second cadence claim follows.

The baseline configuration was restored byte-for-byte and the saved meter profile
preserved. Private evidence: `row-order-rotation-trial-01/result.json` and its
logs/preview in firmware-port-tests. The production meter was not changed.
