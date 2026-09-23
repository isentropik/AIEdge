# First-time configuration

[Back to AIEdge](../README.md) · [Installation](INSTALLATION.md) · [Glossary](GLOSSARY.md)

Installation puts AIEdge on the board. **Configuration sets it up for your particular camera and meter.** Complete this before relying on readings or sending them to Home Assistant.

> The new needle-reading model and calibration were developed for one meter. They are not universal settings. A different meter can require additional calibration and model work. The inherited setup wizard alone does not validate the new polar reading pipeline.

## 1. Keep automatic reading off during setup

The installer starts with **SetupMode enabled** and **LED intensity zero**. SetupMode lets you configure things before automatic readings begin. Some inherited pages still use upstream names and technical labels.

Fix the camera in its final position. Moving it later can change what appears in each reading area.

## 2. Get a clear picture

Open the camera/reference-image settings. A **reference image** is the saved picture used to configure alignment and reading areas.

- Keep the intended dials visible and in focus.
- Adjust camera orientation so the picture is easy to work with.
- Use steady lighting; avoid reflections that hide needle edges.
- Start LED intensity at zero and increase gradually while checking the picture.

For external LEDs, select the actual type, number and channel order. **RGB** has red, green and blue channels; **RGBW** adds a separate white channel. Mixing RGB to make white is different. Check that every LED responds and that zero intensity turns them off. See [lighting details and limitations](../LIGHTING-PORT-STATUS.md).

## 3. Set alignment

**Alignment markers** are fixed features used to line up new pictures with the reference. Choose clear details that do not move, rather than a needle or its shadow.

Alignment helps with small image shifts. It does not sharpen a blurry image or automatically correct every camera angle.

## 4. Define the reading areas

The interface calls these **ROIs**, or *regions of interest*. Each is the part of the picture selected for one reading target, such as a dial.

Check that the areas contain the correct dials. Note whether each needle turns clockwise or counterclockwise; neighboring dials can turn in opposite directions.

The new **polar model** estimates needle position using calibrated geometry. It needs the correct centers and viewing perspective, with the needle pivot kept separate from the dial geometry. This part is currently advanced setup: see [polar configuration](../POLAR-CONFIGURATION.md) and [validation limits](../POLAR-RUNTIME-VALIDATION.md).

Do not copy the development meter's geometry to a different meter and assume the result is accurate.

## 5. Check the units and dial values

A needle position is not yet a consumption measurement. Check the units on your meter and how much one full turn represents.

For the development meter only:

- One full secondary-wheel turn represents **5 cubic feet**.
- One full turn of the last main dial represents **1,000 cubic feet**.
- One numbered step of that main dial represents **100 cubic feet**, or **20 secondary-wheel turns**.

Other meters can have different ratios. A dial going from **9.9 to 0.0** can be normal forward movement; the converted total is what should increase. If pictures are too far apart to know how many whole turns occurred, usage is uncertain and must not be invented. See [calculation details](../METER-ACCOUNTING.md).

## 6. Compare readings with the meter

Compare images and reported readings with what you can see on the physical meter. Include different needle positions and, when available, a crossing through zero. A plausible reading or high model confidence is not proof of accuracy.

Repeat these checks after changing lighting, camera position, alignment or reading areas. Only enable automatic reading once the setup is appropriate for your meter. This preview does not establish accuracy for a new installation.

## 7. Add optional connections

Neither connection below is needed to open the AIEdge website:

- **Home Assistant:** MQTT is a messaging service that can pass readings to HA. You need an MQTT broker, the server that receives these messages, and its connection details. Configure it after checking the readings.
- **Image storage:** off by default. It requires a compatible HTTP(S) upload receiver. An ordinary Windows/SMB network folder alone does not accept this type of upload. See [remote storage](../REMOTE-IMAGE-STORAGE.md).

## After saving a setting

Check whether the change is **applied**, **pending**, **failed** or **restart required**. Saved settings are not always active immediately: some wait for the current reading to finish or require part of the software to restart. Use the reported status rather than repeatedly rebooting. See [technical activation notes](../CONFIG-SAVE-STATUS.md).
