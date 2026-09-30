# AIEdge for Home Assistant

A development app that processes meter images on your Home Assistant server. The
ESP32 supplies pictures; the app aligns the image, estimates the analog dial positions
and calculates a reading from the dial values you configure.

- Images, readings and calibration stay in the app's local storage.
- The interface includes capture history, manual image review, calibration and number formatting.
- Optional MQTT output sends recent register readings to Home Assistant.
- Relative consumption and average rate retain uncertain intervals without guessing
  missed turns; they are not yet published as HA sensors.
- External storage is a future option, not a setup requirement.

**Development status:** the Windows server and local saved-image tests pass. One
Home Assistant Linux amd64 installation has built and started. Its saved reference
image, six-dial calibration and number format survived an app restart. Full Linux
regressions and live camera/MQTT integration still require validation.
This branch is not ready to replace a working meter installation.

[Install the development app](DOCS.md#install-for-a-first-home-assistant-test) · [User guide](DOCS.md) · [Current status](STATUS.md) · [Build notes](PACKAGING.md)

AIEdge builds on [AI-on-the-edge-device](https://github.com/jomjol/AI-on-the-edge-device)
by jomjol and its contributors. Original notices and the project license are preserved
in [Credits](assets/CREDITS.md) and [License](assets/Licence.md).
