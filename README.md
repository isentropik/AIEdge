# AIEdge

Read analog meter dials with an ESP32 camera and process the images on your Home
Assistant server. Images, calibration and reading history stay in the app's local
storage. An external storage server is a future option.

**This branch develops the Home Assistant app.** The local Windows implementation
and saved-image tests pass. Linux, Home Assistant installation and the compatible
ESP32 camera firmware still need validation. It is not a release for replacing a
working meter yet. See [current status](aiedge_app/STATUS.md).

## How it works

- **ESP32 camera:** takes a picture and supplies its capture time and image hash.
- **AIEdge app:** aligns the image, finds the analog needles and converts their
  positions using the dial values you enter.
- **Home Assistant:** can receive recent register readings through optional MQTT.

The app keeps the original images and separates estimates from confirmed labels.
Uncertain readings stay unavailable. Relative consumption and average rate use
capture clocks and configured uncertainty bounds; missed whole turns are not guessed.
These are estimates, not independently verified accuracy or lifetime totals.

## Start here

| What you need | Guide |
| --- | --- |
| Understand setup and saved data | [User guide](aiedge_app/DOCS.md) |
| Check what works and what is still unverified | [Development status](aiedge_app/STATUS.md) |
| Build or test the app | [Build notes](aiedge_app/PACKAGING.md) |
| Implement a compatible camera | [Camera API](aiedge_app/CAMERA-PROTOCOL.md) |
| See the approximate project hours | [Development time](docs/DEVELOPMENT-TIME.md) |

The interface has Overview, Captures, Calibration and Number format, with light,
dark and system themes. Calibration identifies fixed markers and dial geometry.
Number format defines units and the physical value of each full revolution. All
dials constrain one reading; there are no separate main/secondary roles.

The older firmware installer and guides elsewhere in this repository describe the
edition that processes readings on the ESP32. That installer does not install the
new Home Assistant app or establish compatibility with its camera API.

## Credits and license

AIEdge builds on [AI-on-the-edge-device](https://github.com/jomjol/AI-on-the-edge-device)
by jomjol and its contributors, alongside work from Espressif and other component
authors. AIEdge is an independent modified project; upstream does not endorse or
support this development branch. Original notices remain in the source.

See [project credits](CREDITS.md), the unchanged [upstream license](Licence.md),
[packaged source credits](aiedge_app/assets/CREDITS.md) and
[dependency notices](aiedge_app/third-party/README.md). Release packaging still needs
its complete bundled-native and base-system notice review.

AIEdge is being **vibe coded with Codex**, with user direction, image labeling and
hardware testing. The [running hour estimate](docs/DEVELOPMENT-TIME.md) is rounded to
the nearest hour and records this fork's work separately from the upstream project.
