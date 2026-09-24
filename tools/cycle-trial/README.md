# Measure cycle timing

Requires Python 3.10 or newer, with no additional packages. From this directory:

```sh
python collect_cycle_trial.py --origin http://DEVICE-IP --output trial-01
```

Replace DEVICE-IP with your AIEdge address. The output folder must not exist.
Default collection takes about ten minutes (60 polls, ten seconds apart). This
only reads timing records; it does not start captures, change settings or reboot.
Run it while the device is already processing normally.

The report records capture intervals, capture-to-pipeline-finish time, rejected
or failed cycles, missed schedule slots, request latency and per-stage timing.
Repeated polls do not create extra cycles. Stage indexes follow the configured
pipeline; failed attempts and retries are reported separately. Only the last
finished cycle is available on each poll, so missed records and truncated stage
lists are reported explicitly. Different boots are analyzed separately.

A camera-disconnected device can return healthy HTTP responses while recording
no cycles. That is not evidence of 30-second processing. Software acceptance is
not human-verified reading accuracy or proof that MQTT reached Home Assistant.
Socket timeouts bound inactivity, not the total duration of a trickling response.
Three consecutive request errors stop collection. Raw responses and their hashes
are retained for inspection.

Optional Basic-auth credentials use METER_TRIAL_USER and METER_TRIAL_PASSWORD
environment variables. They are not written into reports; use HTTPS when available.

## Before measuring a real meter

Check a current camera image first. All dials and alignment marks must be visible,
and the calibration must match the camera position and image settings. A camera
pointed at a desk, a saved-image diagnostic, or an old cached preview cannot prove
live meter performance. Repositioning a camera may require new calibration; do
not assume the existing six-dial geometry still fits.

Start with one inspected live reading and compare it to the physical dials before
collecting a longer trial. Record lighting, firmware/model/calibration identities,
and whether archiving or other device activity is enabled. Repeat measurements
under the intended workload. The collector does not enable processing, install
calibration, configure publication, or turn on archiving.

The report deliberately leaves `target_achieved` unset. Evaluate successful
capture intervals and capture-to-finish durations alongside failed/missed cycles,
request latency, and any unobserved records. Independently verify readings and
publication at the destination; successful HTTP polls do not establish either.

## Run the offline tests

From the repository root:

```sh
python -m unittest discover -s tools/cycle-trial -p "test_*.py"
```

These tests use constructed telemetry and temporary local files, with no device
requests. They check duplicate polls, restarts, counter regressions, missing
records, malformed data, request failures and bounded polling behavior.
