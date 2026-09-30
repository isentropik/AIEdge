# AIEdge Home Assistant app

AIEdge stores camera images, dial estimates and calibration inside the app's
persistent `/data` directory. No separate storage server or credentials are needed.
External storage is a future optional feature.

## Current development build

The interface includes capture history, reference-image calibration and a number-format
editor. The overview refreshes while it is open, shows local storage health and clears
the displayed reading if the app stops responding. A dark, light or system theme can
be selected at the top of every page. Reloading keeps the selected page.
Use **Refresh** to retry an image that previously could not be loaded. A reference
image that does not load within ten seconds shows a retry message; number-format
fields remain usable while its preview loads.

The native alignment and LiteRT recognition pipeline estimate dial positions. The
number format converts compatible positions to a physical register value. Optional
MQTT output publishes that value to Home Assistant. Overview also tracks relative
consumption and average rate when the capture clocks and configured bounds can
resolve the movement. Camera OTA management remains pending.

This app has not yet been validated inside Home Assistant; do not replace a working
meter with this development build.

Capture starts only when `capture_enabled` is enabled and a camera URL is set.
The existing r60 firmware does not implement the new capture API. Leave capture
disabled until compatible camera firmware is installed. The app does not poll
legacy raw-image or livestream endpoints. Camera credentials go only to the
configured origin; redirects are rejected.
A stalled camera response stops after a 20-second response I/O deadline; the next
scheduled capture can retry. Duplicate or conflicting capture metadata is rejected
before an image is saved. HTTPS still checks the server certificate. Hostname
lookup uses the operating system and can take longer than the response deadline.

## Set up a reading

1. In the app configuration, enter the compatible camera's address. Use its token
   **or** its username and password, depending on its firmware. Keep capture disabled
   while preparing calibration. Changing app options currently requires an app restart.
2. Open **Calibration** and choose a 640 × 480 reference image. Place three separated
   marker boxes on fixed markings, away from needles. Add each dial and mark its rim
   clockwise from zero, then its needle pivot. Up to 16 dials are supported by the
   current physical-reading calculation. **Save calibration** validates the entire
   candidate before replacing the active calibration; it does not restart the camera.
   Drag a crop corner to resize it or drag inside the crop to move it. **Lock proportions**
   keeps its width-to-height ratio while resizing. The editor shows the image alongside
   the controls on desktop; smaller screens place the image above them.
3. Open **Number format**, choose the units printed on the meter and enter the value
   represented by one full revolution of each dial. Focusing a value highlights that
   dial in the reference image. Direction comes from Calibration. All dials participate;
   there are no separate main/secondary roles or per-dial inclusion switches.
4. Save the format, then enable capture when compatible camera firmware is available.
   The default interval is 30 seconds. **Captures** shows original saved images, while
   **Overview** shows the latest processed result and current capture/storage status.

The current **Tolerance** field is an explicit engineering assumption on the 0–10
position scale, not a measured accuracy figure. Validated bounds still need to replace
manual assumptions in the normal setup workflow. The app refuses contradictory or
ambiguous dial combinations. In particular, a small wheel can complete several turns
inside the uncertainty of a larger dial: a single image cannot resolve those turns.
It will show no total rather than invent one. Leading zeros and displayed precision
come from the dial scales, angular resolution and supplied tolerances.

## Review saved images

Open **Captures** and select a photo. Enter each dial position on its 0–10 scale,
using zero for the wrap point. Leave a dial blank when you cannot read it. The form
starts without model estimates filled in, so those estimates cannot become labels
just by clicking Save.

**Dial map** shows the numbered crops on the calibration reference. Use it to identify
the dial names, then return to **Capture** to read the original photo. The app does not
draw reference boxes over a new photo or claim those boxes have been aligned to it.
**Open full image** opens the original at full size for a closer look.

**Save review** stores the image hash, model pipeline, calibration snapshot and entered
positions in the app's local database. Zero and unknown are kept separately. Edits
create new records and preserve earlier versions. Identical photos share one review;
repeated captures do not become independent accuracy evidence. Changing the model or
calibration requires a review for the new setup. A conflicting or unverified save
requires **Reload review** before retrying.

Reviewing does not change the live reading, consumption, training permission or
held-out status. Training admission and near-duplicate checks are still separate;
there is no automatic retraining or verified-accuracy claim. Human entries are private
app data and are not included in the diagnostics download.

## Consumption and average rate

**Consumption** on Overview is the change since a capture anchor, in the configured
meter units. **Average rate** is that change divided by the actual capture interval,
shown per minute. These are estimates under your tolerance and rate assumptions;
they are not a lifetime meter total or independently verified accuracy. Display
precision accounts for uncertainty in both endpoint readings; raw estimates remain
saved separately from their rounded text.

The optional **Maximum rate** in Number format is an upper bound in units per minute.
Leave it empty if you do not know a reliable bound. Without one, images alone cannot
rule out hidden whole-register turns, so the app withholds a consumption point.
A longer gap can remain ambiguous even with a bound. Do not choose a smaller limit
just to make an ambiguous reading appear. Zero means no forward movement is allowed
outside the configured reading uncertainty; clearing the field removes the bound.

All dials constrain the same physical movement. The calculation carries through
rollovers and uses the finest resolved position without adding overlapping dial
fractions twice. For example, a 5 ft³ wheel makes 20 turns for one numbered step
of a 1,000 ft³/revolution dial. Individual phases can wrap from 9.9 to 0 normally.
Contradictory backward movement produces no value. Small jitter is compared with a
fixed anchor rather than added as positive consumption; a decreasing point inside
an overlapping error range is withheld, retaining the range instead of clamping it.
Stationary images do not become new evidence of accuracy.

Capture time comes from the camera's same-boot monotonic tick, not the image download
time. Rejected images preserve the last usable observation. A camera change, missing
or inconsistent timing, a rebooted camera, or a change to calibration, physical format
or accounting software starts a separate relative segment. Previous records stay
saved. An app restart on the same camera clock replays the saved decisions; it does
not add the consumed volume again. A damaged accounting record is kept and blocks
consumption until storage is repaired or restored. The app never resets it silently.

Consumption and average rate are currently shown only in AIEdge. MQTT still publishes
the register reading; no cumulative sensor or `total_increasing` entity is created.

## Send readings to Home Assistant

MQTT output is optional and off by default. When testing inside Home Assistant, use a
Supervisor-managed MQTT broker and enable `mqtt_enabled` in the app configuration.
The app obtains the broker connection through Supervisor; it does not ask for a
separate storage server. Camera images stay in app storage and are not sent over MQTT.

AIEdge creates a distinct **Meter reading** sensor through MQTT discovery. It publishes
only a recent estimate tied to the latest captured image and current number format.
Rejected, stale or ambiguous readings make it unavailable. It does not replace existing
meter entities or claim that estimates are verified. Changing units or physical scales
creates a new sensor identity so previous history is not reinterpreted; the earlier
entity remains unavailable and can be removed manually from Home Assistant.

This is a register position, not yet a validated cumulative-consumption sensor, so it
is not marked `total_increasing` for long-term statistics. Actual Supervisor and MQTT
integration testing is pending. The local test uses Paho with a loopback protocol
fixture, not the user's Home Assistant broker.

## Saved data and backups

- `images/`: original JPEGs, identified and verified by SHA-256.
- `captures.sqlite3`: capture timestamps, receipt times, errors, model estimates and
  relative consumption segments/decisions.
- `references/` and `calibration.json`: reference images and saved calibration.
- `instance-id`: stable identity used for MQTT discovery, if MQTT is enabled.
- `recovery/`: hash-verified copies of damaged setup files replaced through the editor.
- `reading-format.json`: optional physical scales and uncertainty bounds, tied to
  the active model and calibration pipeline.

Identical images share one file while retaining their separate capture events.
All collected images are unlabeled and excluded from training until reviewed.
Model estimates are not verified labels or evidence of reading accuracy.

Include AIEdge when selecting apps for a Home Assistant backup. The app is configured
for a cold backup: Supervisor stops it during the backup so the database and image
files cannot change while being copied. Captures pause during that time. Images are
not excluded, so backup size will grow with the stored collection. A local stopped-app
copy/restore test passes; a real Supervisor backup/restore still needs validation.

New captures wait when less than 512 MiB plus one maximum-size image remains free
on the data filesystem. They resume at a later scheduled check after space is
available. This is a headroom check, not a disk quota: other apps can consume the
same disk. Existing images are never automatically deleted. Automatic retention
controls are not implemented yet. The status API reports remaining free bytes and
whether storage is ready, low on space or unavailable.

The app exposes no host port. Ingress access is restricted to the Supervisor proxy.
Native development binds to localhost by default. See `CAMERA-PROTOCOL.md` for the
camera API and `PACKAGING.md` for build details.

## Recover saved setup

If a saved calibration or number-format file is damaged, the app stays open and shows
which part needs attention. Recognition or physical conversion remains unavailable
until that part is repaired. Save a valid replacement in the relevant editor; the app
preserves the original bytes in `recovery/` before replacing them. It will refuse the
save if it cannot preserve the original or the file changed since startup.

A missing reference image requires choosing the reference again and checking its
markers and dials. A missing recognition library or model requires fixing the app
installation; re-entering calibration cannot repair those files. If the data directory
cannot be read, fix storage access and restart the app. These recovery controls do
not repair a damaged database or replace a Home Assistant backup.

A damaged stored inference result is kept for diagnosis and shown as unavailable.
It is not counted as a successful reading or silently replaced by an older result.
Recognition gives the newest capture priority, then processes remaining history
oldest first. Calibration changes do not make the current reading wait behind a
large archive.

## Capture history and diagnostics

Use **Older** and **Newer** on Captures to browse beyond the latest 50 events.
Each card separates the camera's capture time from the app's receipt time.
A history-loading error stays on Captures; it does not hide a successful current
reading on Overview. Use **Refresh** to retry while keeping already-loaded images.
**Repeated image** means its JPEG is identical to an earlier one; the capture
is still retained as a separate timestamped event. It is not new accuracy evidence.

**Download diagnostics** on Overview saves a local JSON report with runtime
versions, storage health, capture counts, capture-clock continuity, setup and
consumption-engine status. It excludes passwords,
camera addresses, images, dial positions, meter values and local paths. Nothing
is uploaded automatically. The report is also available when the database cannot
open, as long as the app process can start.

Invalid app options stop capture and MQTT while leaving the website available.
Correct the options in Home Assistant and restart the app. A damaged MQTT identity
must be restored from backup; the app will not invent a replacement and split the
sensor's history. If the database cannot open, fix the data volume or restore a
backup, then restart. The app does not automatically reset or repair the database.

Normal shutdown stops new work and allows up to 25 seconds total for active web
requests and workers to finish. Idle HTTP connections time out after ten seconds,
and the app admits at most 32 concurrent requests. At capacity, ordinary requests
receive a temporary busy response and the interface retries. A timeout exits with an error. A forced process kill or power loss cannot
be made graceful; database transactions and verified image writes remain necessary.
Actual Supervisor stop and backup behavior still requires Linux validation.

On Linux, new image and setup-file directory entries are flushed before a successful
save is reported. If that flush fails after a settings rename, the file may already
have changed: reload or restart to read it back before retrying. An error is not a
promise that the old file remains active on disk. Windows tests cannot establish
Linux power-loss durability, and physical power-loss recovery remains unverified.
