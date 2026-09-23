# Analog-reader diagnostics

These development checks compare the ESP32 implementation with frozen reference data. They do not establish meter-reading accuracy.

- `POST /polar_runtime_test` runs six precomputed input tensors through the frozen model. Read results with `GET /polar_runtime_test`.
- `POST /polar_frame_test` starts with a fixed 640 × 480 RGB image, performs marker registration and preprocessing for all six dials, then compares the feature bytes and model outputs. Read results with `GET /polar_frame_test`.

Both POST requests require an empty body and no query parameters. They start a background task; GET only reads its status. A diagnostic refuses to run when normal processing or camera access is busy. It does not publish meter readings, update consumption, train the model or force a camera capture.

The full-frame check requires a matching, verified `diagnostics/polar-runtime-frame.rgb` fixture in the selected application bundle. Private meter images are not public release assets. A build without this fixture reports `full_frame_fixture_rejected`; it must not fall back to an unrelated SD file.

The reported full-frame processing duration covers registration, preprocessing and inference. It excludes fixture verification/loading, camera exposure/capture, JPEG decoding, and result publication. The response explicitly reports `camera_capture_tested: false` and `verified_accuracy: false`. Measure the live capture-to-publication path separately before claiming the 30-second target.

A byte mismatch is evidence to investigate, not permission to change expected outputs or retrain on the held-out image.

The full-frame diagnostic holds the processing and camera locks because image decoding and inference share reserved memory. Its RGB fixture uses the unused verified-model workspace; a separate smaller allocation holds preprocessing buffers. Allocation failures are reported without publishing a reading or restarting the device.
