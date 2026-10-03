# Take a short review batch

A trial collects a few camera pictures for checking your setup. It does not turn
on the capture schedule, publish to MQTT, copy to a network share, or train a model.

1. Finish Setup and Number format. Enter your compatible camera's address and
   credentials in the app options if needed. App option changes require an app
   restart; this does not restart the camera.
2. Leave automatic capture, MQTT and network copying off.
3. Open **Captures** and select **Start trial**. The trial makes at most three
   capture attempts, normally 30 seconds apart, using your saved camera settings.
4. Watch progress or select **Stop**. A picture already being transferred may
   finish and be kept. Stopping prevents the next request.
5. Select a saved photo in Captures to enter the dial positions you can read.
   Leave unreadable dials blank. Reviews do not replace readings or train the model.

Progress separates attempts, unique images and repeats. Three attempts can yield
fewer than three saved photos or different needle positions. Repeated images are
not additional accuracy evidence. Counts may be incomplete after interrupted work.

## If something goes wrong

The app checks the saved request after a lost connection; it does not silently
start another trial. **Retry start**, when offered, uses that same request ID.
Keep this browser tab while checking an uncertain request. If browser storage is
unavailable, enable it and reload before starting. Opening or reloading Captures
does not take a picture. App restarts leave unfinished trials interrupted rather
than resuming them.

The acquisition request budget is 90 seconds. A slow transfer skips missed slots
instead of queuing captures. A failed or uncertain capture stops the trial.
Operating-system DNS, storage stalls or suspended processes can outlast the
request budget; it is not a promise that all cleanup finishes within 90 seconds.

Missing or discontinuous capture timing stops the trial after preserving a
verified raw photo. Receipt times cannot replace capture times for consumption.
Do not infer skipped full turns from endpoint wheel positions alone. Images
remain excluded from training until review and split checks are complete.

If trial storage cannot be verified, Start is disabled and the original record is
kept. Check app diagnostics and restore from a verified backup when appropriate;
do not delete the journal to force a retry. Calibration, model or number-format
changes stop an active trial. Camera light and image settings use the same guards
as normal captures.

This is an experimental feature. Host and simulated-browser checks do not prove
camera-to-HA timing, physical light behavior, recognition accuracy or hardware
recovery. Check the exact draft's CI and deployment results before relying on it.
