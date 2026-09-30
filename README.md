# AIEdge for Home Assistant

AIEdge processes analog meter images on your Home Assistant server. An ESP32 camera
supplies pictures; the app aligns them, estimates needle positions and calculates
readings from the dial values you define. Images and calibration stay in the app's
local storage. An external storage server is not required.

This branch contains the **experimental Home Assistant app**. The ESP32 firmware
project remains on [the firmware branch](https://github.com/isentropik/AIEdge/tree/codex/aiedge-publication).

## Install the development app

On Home Assistant OS with an **amd64** host, open **Settings → Apps → Install app**.
Choose **⋮ → Repositories** and add this exact URL:

```text
https://github.com/isentropik/AIEdge#codex/aiedge-ha-app
```

Select **AIEdge → Install → Start → Open Web UI**. Installation builds the container
on your HA host and can take several minutes. For the first test, leave camera
capture and MQTT disabled and use a saved image in Calibration.

[Installation and user guide](aiedge_app/DOCS.md) · [Current status](aiedge_app/STATUS.md) ·
[Build and test instructions](aiedge_app/PACKAGING.md)

## What is available

- A compact interface with desktop, tablet and phone layouts, plus light/dark themes.
- Local capture history and human image review with immutable revisions.
- Reference-image calibration, separate needle pivots and three alignment markers.
- Generic per-dial revolution values, number formatting and conservative consumption accounting.
- Optional MQTT register readings; uncertain intervals stay explicit.

## Test status

The development container has built and started on Home Assistant's Linux amd64
host. Read-only HA checks confirmed the UI routes, empty storage and disabled camera
and MQTT. Saved-image calibration and persistence inside HA are still pending.
Windows tests use the actual native pipeline and pinned models. Synthetic tests and
unlabeled estimates do not establish recognition accuracy. This is not a validated
release or a replacement for a working meter installation.

The existing r60 firmware does not implement the new remote-camera API; do not
point enabled app capture at that firmware. ARM/Raspberry Pi builds are not provided yet.

## Credits

AIEdge builds on [AI-on-the-edge-device](https://github.com/jomjol/AI-on-the-edge-device)
by jomjol and its contributors. Their license and notices remain in the
[credits](aiedge_app/assets/CREDITS.md) and [license](aiedge_app/assets/Licence.md).

This fork is being vibe coded with Codex, with user direction, labeling and hardware
testing. The approximate recorded project time is tracked in
[Development time](docs/DEVELOPMENT-TIME.md).
