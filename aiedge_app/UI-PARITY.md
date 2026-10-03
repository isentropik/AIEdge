# App interface and camera controls

The app uses a compact sidebar and a theme selector at the top. Setup contains
Meter, Lighting, Image, Alignment, Dials, Number format, Data and Finish. Next applies
the relevant choices. Finishing does not restart the camera, enable scheduled
captures or publish readings.

| Previous setup feature | App behavior |
| --- | --- |
| Meter and units | Gas, Water or Electric with supported units. Metadata saves without a camera or reference; new units require reviewing the number format before affecting readings. |
| Lighting | Explicitly load saved lighting. Select the built-in LED or a supported strip, GPIO, pixel type and count. RGBW offers dedicated white, RGB or a custom channel mix. |
| Brightness | One 0–100% control on Image scales the selected light. White mode hides RGB controls; custom mix shows numeric channels without a color chooser. |
| Reference image | Choose a saved 640 × 480 image, use the latest stored capture, or explicitly take a picture. An unchanged reference is retained. |
| Alignment | Three markers on fixed print, X/Y coordinates, proportion lock and marker suggestions. |
| Analog dials | One selector for every dial, including a small wheel. Crop, rename, CW/CCW, four rim landmarks and a separate needle pivot. |
| Number format | Physical value per revolution, units and highlighted dial locations. No sample digits, display-digit count, inclusion controls or adjustable tolerance. |
| Image viewing | Grid, zoom and fit icons. The image stays beside controls on desktop and visible while scrolling controls on mobile. |
| Crop and rotation | Drag crop corners, rotate by quarter turns and straighten immediately. Next saves the app framing; no replacement picture is required. Original pixels and source landmarks are preserved. |
| Auto | The Auto switch hides manual controls and brightness. Take picture searches for a usable light/exposure pair on supported firmware. The camera type stays visible beside the switch. |
| Data | Original images and readings stay in Home Assistant app storage. Storage health and MQTT state are shown. |
| Overview and history | Physical reading, individual estimates, consumption state, capture history and manual review. Unknown or ambiguous data stays explicit. |

## Applying lighting

Crop and rotation belong to app framing. They do not write camera settings.
Saved framing is used by Image, Alignment, Dials and the Number format reference
preview. Stored captures and manual reviews retain their original images.

Load camera settings is a read-only action; opening a page does not contact the
camera. Next on Lighting saves changed choices and activates them without a
restart. Taking a picture also applies pending lighting choices first. Changing
a control alone does not write to the camera or take a picture.

Unchanged lighting produces no SD write and no activation request. Changed
configuration is checked against the exact saved baseline, edited without altering
unrelated bytes, read back, explicitly activated, and read back again. Only lighting
fields reach the browser; raw configuration and credentials remain in server memory.

If a write or activation cannot be verified, an app-side intent record survives
restart and blocks new photos and scheduled captures. Load the saved settings,
review them, then explicitly activate them. The app does not blindly retry a write
or silently roll it back. A successful handler response verifies saved configuration
and reported activation, not physical brightness or reading accuracy.

## Exposure, gain and orientation

Load camera controls reads settings without taking a picture. The camera must
advertise the exact supported contract. Unknown or older firmware remains usable
for saved-image setup; unavailable sensor controls cannot claim activation.

Auto is a saved app preference, separate from the sensor's automatic exposure and
gain settings. Take picture tests light and exposure while keeping gain at zero,
saves the selected pair together, then takes a normal reference picture. Auto
stays selected even when it chooses a fixed exposure. Trial pictures never become
readings or training evidence. Image quality checks are a heuristic, not a
measurement of recognition accuracy or sensor noise.

Manual mode exposes separate automatic exposure/gain switches, exposure, exposure
correction, extra sensor exposure correction, gain and its limit. Applicable
controls are shown together rather than behind a second advanced section.

Manual slider edits do not capture or write. Take picture applies changed choices
without a restart, checks exact saved bytes and activation, then takes one photo.
Brightness and sensor changes dim the current photo until that explicit capture.
Changing a choice back before applying it does not require another picture.

Flip icons preview immediately after a photo whose orientation has been verified.
An uploaded or legacy image has no assumed orientation. Changing sensor orientation
requires a matching new photo and calibration before scheduled captures resume.
The flip preview disappears on Alignment so coordinates refer to actual pixels.
Replacing the reference clears old landmarks and its preview orientation baseline.

## Remaining camera controls

The app integrates the installed camera's lighting-capabilities, configuration-save
and apply-lighting handlers. A camera without them shows an unsupported message.
External PWM lighting and ambiguous configurations are not converted automatically.
No camera firmware update is included.

Other sensor adjustments, JPEG quality and sensor cropping remain outside this
app contract. App framing changes how the reference is displayed; recognition
continues using original pixels and source coordinates. Stored captures and manual
review show their originals. Grid, zoom and fit are view controls; dial crop edits
affect recognition calibration. Physical sensor/lighting verification and
production firmware startup recovery remain prerequisites to a live firmware update.

## Failed Auto operations

The app requires firmware advertising temporary captures with restoration before
the response. Unsupported firmware offers manual setup; it cannot silently fall
back to a sensor-only approximation of Auto.

A lost or invalid trial reply leaves a durable capture block. Restarting the app,
loading settings or turning Auto off does not remove it. Reload saved settings and
explicitly restore them on the same camera. The app accepts only the known old or
new configuration revision, verifies activation and exact readback, and never
resubmits the trial or an uncertain save. A pending orientation change still needs
a matching reference and calibration before scheduled capture can resume.

Auto progress stays inside the image area. A failed final reference leaves the
current reference intact. Original trial bytes and hashes are retained separately
under `auto-trials`, with bounded storage and no automatic deletion.

## Setup photos

Taking a setup photo is an explicit action. The app checks readiness, requests one
picture, verifies its hash and timestamps, and stores a reference candidate. It
never uses a filename or estimate as a label. The photo is not a scheduled reading,
consumption observation or accuracy result. Busy or failed requests are not retried.

Lighting edits gray the existing image and highlight the centered Take picture
button. Returning to the saved choices clears this state. An unchanged image is
retained when continuing; a different reference requires fresh geometry.

The browser checks cached job status while an explicit operation is pending. The
loading overlay covers only the image. Other app pages remain available. Changing
app configuration, including the camera address or MQTT options, currently requires
restarting AIEdge, not the camera. Calibration and number format apply without
restarting either. Capture and MQTT are never enabled by setup.
