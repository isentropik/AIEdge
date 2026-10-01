# App interface and camera controls

The app uses a compact sidebar and a theme selector at the top. Setup contains
Lighting, Image, Alignment, Dials, Number format, Data and Finish. Next applies
the relevant choices. Finishing does not restart the camera, enable scheduled
captures or publish readings.

| Previous setup feature | App behavior |
| --- | --- |
| Lighting | Explicitly load saved lighting. Select the built-in LED or a supported strip, GPIO, pixel type and count. RGBW offers dedicated white, RGB or a custom channel mix. |
| Brightness | One 0–100% control on Image scales the selected light. White mode hides RGB controls; custom mix shows numeric channels without a color chooser. |
| Reference image | Choose a saved 640 × 480 image, use the latest stored capture, or explicitly take a picture. An unchanged reference is retained. |
| Alignment | Three markers on fixed print, X/Y coordinates, proportion lock and marker suggestions. |
| Analog dials | One selector for every dial, including a small wheel. Crop, rename, CW/CCW, four rim landmarks and a separate needle pivot. |
| Number format | Physical value per revolution, units and highlighted dial locations. No sample digits, display-digit count, inclusion controls or adjustable tolerance. |
| Image viewing | Grid, zoom and fit icons. The image stays beside controls on desktop and visible while scrolling controls on mobile. |
| Data | Original images and readings stay in Home Assistant app storage. Storage health and MQTT state are shown. |
| Overview and history | Physical reading, individual estimates, consumption state, capture history and manual review. Unknown or ambiguous data stays explicit. |

## Applying lighting

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

## Remaining camera controls

The app integrates the installed camera's lighting-capabilities, configuration-save
and apply-lighting handlers. A camera without them shows an unsupported message.
External PWM lighting and ambiguous configurations are not converted automatically.
No camera firmware update is included.

Exposure, gain and sensor orientation remain on the camera website pending a
tested app management contract. Rotation, flips and sensor cropping must affect
subsequent pictures as well as the reference. Editing only the reference would
give alignment a different coordinate system from incoming captures. Grid, zoom
and fit are view controls; dial crop edits affect recognition calibration.

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
