# AIEdge Home Assistant app

AIEdge stores camera images, dial estimates and calibration inside the app's
persistent `/data` directory. No separate storage server or credentials are needed.
Optional archive copies use an SMB or NFS share mounted by Home Assistant.

## Optional network archive

You can leave this off. Images, readings and calibration continue to use AIEdge's
local app storage.

1. In Home Assistant, open **Settings â†’ System â†’ Storage â†’ Add network storage**.
   Give it a name such as `meter_archive` and choose **Media** for usage.
2. Enter the storage server's IP address or hostname. For a Windows/SMB share,
   choose **CIFS**, enter its share name, username and password, then connect.
   NFS shares are supported too. Home Assistant manages the connection and login;
   no extra receiver, access token or Docker service is needed.
3. Open **AIEdge â†’ Setup â†’ Data**, enable **Copy to network storage**, and enter
   the mounted folder, for example `/media/meter_archive`. To use a folder within
   that share, append it, for example `/media/meter_archive/aiedge`.
4. Select **Next**. Stored captures and subsequent captures are queued for copying.
   The page shows verified copies, waiting captures and any connection problem.

For `\\unraid\backups\aiedge`, the Home Assistant server is `unraid`, the share
is `backups`, and the AIEdge folder is `/media/<storage-name>/aiedge`.
The app accepts only mounted network filesystems below `/media`; it does not open
a Windows UNC path directly or fall back to writing in an unmounted local folder.

Archive files are stored under `<folder>/aiedge/<app-instance>/`. `objects/`
contains original JPEGs keyed by SHA-256; `events/` retains each capture's frame
identity, capture and receipt timestamps, and any camera monotonic-clock metadata.
Identical JPEGs share an object while keeping separate capture events. Credentials,
model predictions and human labels are excluded. These copies are not permission
to train: `training_allowed` and `accuracy_verified` remain false, and their split
status is unchecked. Keep existing held-out and near-duplicate protections when
later importing them into a training dataset.

Copies run separately from capture, inference and HTTP requests. A slow or absent
share causes bounded retries; a conflicting remote file or corrupt local image
requires inspection and an explicit **Retry copies**. Disabling copies stops new
work, but an in-progress remote write can finish. Local and remote images are
never deleted by archiving. Restarting resumes from verified acknowledgements;
an interrupted copy is rechecked rather than counted as successful. NAS power-loss
durability still depends on the server and storage honoring flush requests.

[Home Assistant network-storage instructions](https://www.home-assistant.io/common-tasks/os/#network-storage)

Development status: the archive implementation is prepared locally. A real SMB/NFS
mount and deployed end-to-end copy have not yet been verified.

## Install for a first Home Assistant test

This is an experimental **amd64** build for Home Assistant OS. One Linux amd64
installation has built, processed saved images and retained six-dial calibration
and number format after restarts. A September 30 dev8 trial received three photos
about 30 seconds apart with no transfer failures. This short trial does not verify
sustained operation or reading accuracy. Dev10's Linux regressions and packaged
startup checks passed; end-to-end MQTT integration remains unverified.
Installation builds the app on your HA host and can take several
minutes; check the app logs if it fails.

1. Open **Settings â†’ Apps â†’ Install app**. From the three-dot menu, choose
   **Repositories** and add this complete URL, including the branch after `#`:

   ```text
   https://github.com/isentropik/AIEdge#codex/aiedge-ha-app
   ```

2. Refresh the store, choose **AIEdge**, and select **Install**.
3. Leave `capture_enabled` and `mqtt_enabled` off and the camera address blank.
   Select **Start**, then **Open Web UI**. Enable **Show in sidebar** if desired.
4. Check that Overview, Captures, Setup, Number format and Settings open. For the
   initial test, choose a saved reference image in Setup; no live camera is
   needed. Images and app settings stay in HA app storage.
5. Restart only the AIEdge app and verify your saved calibration and number format
   remain. If startup or a page fails, use the app's **Log** tab for the error.

This first test checks installation, the interface and persistence. It does not
verify meter accuracy. Live capture requires a camera running AIEdge's remote-camera
API; stock AI-on-the-edge firmware does not provide it. Existing HA entities
are unchanged with MQTT disabled. An amd64 host is currently required; ARM/Raspberry
Pi builds are not provided.

[Home Assistant app installation](https://www.home-assistant.io/apps) Â·
[Development source](https://github.com/isentropik/AIEdge/tree/codex/aiedge-ha-app)

## Current development build

The server app samples each dial at full resolution. It uses the same trained
needle models; edge detection is not the production reader. New processing versions
have distinct identities, so an old number format cannot silently publish values
for changed processing. Review and save Number format when the app requests it.

The interface includes guided setup, capture history, reference-image calibration,
number formatting and Settings. Next applies the relevant setup step; there is no
camera restart when setup finishes. The overview refreshes while it is open, shows local storage health and clears
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

The saved-image processing and persistence test passed inside Home Assistant, with
capture and MQTT disabled. End-to-end camera/MQTT checks remain pending; do not
replace a working meter with this development build.

After recognition code, native libraries or models change, the pipeline identity
changes too. Review **Number format** and save the same dial values for the new
pipeline before enabling capture or MQTT. A stale format is withheld rather than
silently applied to a different pipeline.

Capture starts only when `capture_enabled` is enabled and a camera URL is set.
Each scheduled cycle first checks `GET /api/v1/camera`. It requests a picture only
when the camera reports ready settings, synchronized time and an available camera.
An unready or unreachable camera is checked again at the next scheduled cycle;
there is no immediate retry loop. This readiness snapshot does not guarantee that
the subsequent capture will succeed. Firmware must provide both the status and
capture APIs. The local command-line camera checker uses the same status parser.
The existing r60 firmware does not implement the new capture API. Leave capture
disabled until compatible camera firmware is installed. The app does not poll
legacy raw-image or livestream endpoints. Camera credentials go only to the
configured origin; redirects are rejected.
A stalled camera response stops after a 20-second response I/O deadline; the next
scheduled capture can retry. Duplicate or conflicting capture metadata is rejected
before an image is saved. HTTPS still checks the server certificate. Hostname
lookup uses the operating system and can take longer than the response deadline.

## Set up a reading

Before starting, enter the compatible camera's address in app configuration.
Use its token **or** its username and password, depending on its firmware. Keep
capture disabled while preparing calibration. Changing app options currently
requires an app restart. Saved-image setup does not need a camera address.

1. In **Meter**, select Gas, Water or Electric and the units printed on the meter.
   You can revisit these choices later. Existing units do not identify the meter type.
2. Open **Setup â†’ Lighting** and explicitly **Load camera settings** if a camera is
   configured. Select the installed light, strip type/count and white or RGB mode.
   Next saves changed lighting and activates it without restarting the camera.
   With no camera configured, continue using saved images.
3. In **Image**, choose a saved 640 Ã— 480 image or use the latest stored
   capture. With a compatible camera configured, **Take picture** requests one photo.
   Opening a page does not take a photo. An unchanged reference carries forward;
   replacing it with a different image requires new markers and dial geometry.
4. Select **Next** to open **Alignment**. Place all three markers on fixed print,
   spread across the image and away from needles or reflections. Use X/Y and size
   fields, or drag a box. Marker suggestions are available once dial crops exist.
5. In **Dials**, use the selector to edit every dial, including the small wheel.
   Draw a crop, mark four rim points clockwise from zero, then place the needle pivot.
   Select CW or CCW to match the printed scale. **Lock width / height** preserves
   proportions while resizing. Next validates the whole calibration before replacing
   the active one. Up to 16 dials are supported.
6. In **Number format**, enter the value in your selected units
   represented by one full revolution of each dial. Focusing a value highlights that
   dial in the reference image. Direction comes from Dials. All dials participate;
   there are no separate main/secondary roles or per-dial inclusion switches.
7. **Data** shows local storage, optional network copying and MQTT state.
8. **Finish** summarizes saved choices.
   Open Overview when finished; the camera does not restart. Enable capture in app
   configuration when compatible camera firmware is available.
   The default interval is 30 seconds. **Captures** shows original saved images, while
   **Overview** shows the latest processed result and current capture/storage status.

Changing units keeps the current readings in their original units until you apply
a new number format. AIEdge clears the dial-value fields for the new units so you
can enter them explicitly. It does not convert or relabel old readings automatically.

Desktop setup keeps the image beside its controls. Mobile places it above them and
keeps it visible while you scroll the controls. Grid, zoom and fit change only the
view. Image contains one brightness control for the selected light. A lighting
change grays the previous photo and highlights Take picture; unchanged choices
retain the existing reference. Failed or uncertain lighting activation blocks new
captures until you load and explicitly activate the saved choices. Compatible
firmware also exposes exposure, gain and sensor orientation in Image.
See [UI parity](UI-PARITY.md) for supported handlers and remaining controls.

There is no tolerance or accuracy control in setup. Editing physical dial values
preserves the saved reader's uncertainty assumptions. New formats currently use
an internal provisional Â±0.1 bound on the 0â€“10 position scale. This is not measured
model accuracy; validated model/calibration error still needs to replace it.
The app refuses contradictory or
ambiguous dial combinations. In particular, a small wheel can complete several turns
inside the uncertainty of a larger dial: a single image cannot resolve those turns.
It will show no total rather than invent one. Leading zeros and displayed precision
come from the dial scales, angular resolution and internal error assumptions.

## Review saved images

Open **Captures** and select a photo. Enter each dial position on its 0â€“10 scale,
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
shown per minute. These are estimates under internal error and configured rate assumptions;
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
fractions twice. For example, a 5 ftÂ³ wheel makes 20 turns for one numbered step
of a 1,000 ftÂ³/revolution dial. Individual phases can wrap from 9.9 to 0 normally.
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
- `meter-profile.json`: meter type and preferred units, independent of calibration.
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


## Updating from dev19 to dev20

This update changes the main-dial model. Your original images, reference, dial
regions, alignment markers, units and saved history are retained. Old model
results and reviews keep their original identity in history.

After updating, open **Number format**, check the existing dial values and unit,
then save it to use the new reader. Until that save, current readings and
consumption are unavailable. Saving starts a separate consumption segment;
previous consumption history remains available, but an old anchor is not carried
across the model change. A reading that is still ambiguous stays ambiguous.

The update does not enable scheduled capture, MQTT or network archiving. It does
not change the camera firmware, lighting or exposure. Saved-image tests do not
establish accuracy for unseen meters or lighting conditions.
