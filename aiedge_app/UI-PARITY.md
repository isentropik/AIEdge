# App interface and camera controls

The app uses a compact sidebar, a theme selector at the top, and the same controls
on desktop and mobile. Setup is divided into Image, Alignment, Dials, Number
format, Data and Finish. Next applies the relevant choices. Finishing setup does
not restart the camera, enable scheduled captures or publish readings.

| Previous setup feature | App behavior |
| --- | --- |
| Reference image | Choose a saved 640 × 480 image, use the latest stored capture, or explicitly take a picture with a configured compatible camera. An unchanged reference is retained. |
| Alignment | Three markers on fixed print, X/Y coordinates, proportion lock and marker suggestions. |
| Analog dials | One selector for every dial, including a small consumption wheel. Crop, rename, CW/CCW, four rim landmarks and a separate needle pivot. |
| Number format | Each dial's physical value per revolution, meter units and highlighted dial locations. No sample digits, display-digit count, inclusion controls or adjustable tolerance. |
| Image viewing | Grid, zoom and fit icons. The image stays beside controls on desktop and stays visible while scrolling controls on mobile. |
| Data | Original images and readings stay in Home Assistant app storage. Storage health and MQTT state are shown. |
| Overview and history | Current physical reading, individual estimates, consumption state, capture history and manual review. Unknown or ambiguous data stays explicit. |
| Camera and lighting | Open the configured camera's website from Settings. The app does not yet change camera settings. |

## Camera controls are still separate

The installed remote-camera protocol provides readiness and capture endpoints. It
does not provide safe management endpoints for LED type/count, RGB versus the
dedicated white channel, intensity, automatic exposure/gain, or camera-side
orientation. These controls have not been replaced with inactive app controls.

Set those choices on the camera before taking the reference. Camera rotation,
flips and sensor cropping must affect subsequent pictures as well as the reference.
Editing only the reference would give alignment a different coordinate system
from incoming captures. Grid, zoom and fit in the app are view controls; they do
not rotate, flip or crop incoming images. Dial crop edits affect the actual
recognition calibration.

This candidate restores the app's guided calibration, formatting, review and
navigation flows. It is not complete parity with the camera's management UI.
Camera-management integration and image transforms remain separate work requiring
a defined, tested settings contract. No camera firmware update is included.

## Setup photos

Taking a setup photo is an explicit action. The app checks camera readiness,
requests one picture, verifies its hash and capture timestamps, and stores a
reference candidate. It never uses the filename or an estimated reading as a label.
It does not count the photo as a scheduled reading, consumption observation or
accuracy result. A busy or failed request is not retried automatically.

The browser checks the app's cached job status while a requested photo is pending.
The image alone shows the loading overlay; other app pages remain available.
Opening a page only reads local app data and cached camera configuration.

Changing app configuration, including the camera address or MQTT options, still
requires restarting the app. Calibration and number-format changes apply in the
app without restarting the camera. This UI candidate does not enable capture or
MQTT automatically.
