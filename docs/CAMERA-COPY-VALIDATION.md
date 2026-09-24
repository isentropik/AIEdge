# Camera RGB copy

The normal camera path now copies the validated contiguous RGB buffer in one
operation instead of traversing columns and assigning individual channels.
No sampling, resolution, color conversion or model changes are involved. Existing
destination capacity and source geometry checks remain in place.

Fifteen actual-function host cases pass, including comparison of every byte in a
640x480 RGB frame (921,600 bytes), geometry/buffer checks, failed capture/decode,
lighting errors and invalid timestamps. Camera and decoder boundaries are simulated.
Run the public test under `tools/camera-tests`; the ESP32 build also passed.

The managed test-board update is installed and verified:
`b8f5766e0266a93d9a83cf6be573a8a89cf08623ffcb4baac7dde47ca95fa25f`.
Configuration, meter profile and authentication were preserved.

One normal camera cycle at 160 MHz measured the capture stage at **4.671760 s**,
compared with **6.875065 s** in the earlier baseline with the same trial settings.
These are individual observations, not a controlled distribution or a guaranteed
speedup. The stage includes lighting wait, camera acquisition, decoding and copying.
The subsequent alignment stage measured 3.919806 s; polar registration rejected
the scene because this test camera was not viewing the calibrated meter.
No accepted reading or sustained 30-second cadence is established by this test.

The original configuration was restored byte-for-byte and the profile preserved.
Private evidence is under `camera-bulk-copy-trial-01` in firmware-port-tests.
Production was not changed.

A second bounded cycle with temporary DEBUG logging measured the contiguous copy
itself at **198,498 microseconds (0.198498 s)** for 921,600 bytes. Its complete
capture stage was 5.001272 s. Logging changes and camera variability mean this
second run is not a directly controlled before/after comparison. Baseline settings
were again restored and the profile preserved. Evidence: `camera-bulk-copy-debug-01`.
