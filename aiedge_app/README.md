# AIEdge for Home Assistant

A development app that processes meter images on your Home Assistant server. The
ESP32 supplies pictures; the app aligns the image, estimates the analog dial positions
and calculates a reading from the dial values you configure.

- Images, readings and calibration stay in the app's local storage.
- Guided setup covers reference images, three alignment markers, analog dials,
  number format and local data. Capture history, review and Settings use the same UI.
- Optional MQTT output sends recent register readings to Home Assistant.
- Relative consumption and average rate retain uncertain intervals without guessing
  missed turns; they are not yet published as HA sensors.
- Optional SMB/NFS archive copies use Home Assistant network storage. Local storage remains the default; see [setup instructions](DOCS.md#optional-network-archive).

**Development status:** dev28 passed its merged-head Linux CI and a controlled
Home Assistant installation preserved saved data through restart. Dev29 is a local
candidate and still needs its own exact-head Linux/package validation. Recognition
accuracy, physical cumulative consumption, sustained capture cadence, live output
and camera recovery remain open.
This branch is not ready to replace a working meter installation.

Dev29 adds an explicit Home Assistant option for last-two-dial event recognition.
Full recognition remains the default. The option preserves the fixed capture
schedule, checks alignment on every image and falls back to full observations
when the optimization is unavailable or uncertain. It does not enable capture
or publication. See [recognition mode](DOCS.md#recognition-mode-dev29) for setup
and the required restart/edit workflow. Numerical dial configuration is generic;
optical accuracy on another meter still requires evaluation.

[Install the development app](DOCS.md#install-for-a-first-home-assistant-test) · [User guide](DOCS.md) · [UI features and remaining camera controls](UI-PARITY.md) · [Current status](STATUS.md) · [Build notes](PACKAGING.md)

AIEdge builds on [AI-on-the-edge-device](https://github.com/jomjol/AI-on-the-edge-device)
by jomjol and its contributors. Original notices and the project license are preserved
in [Credits](assets/CREDITS.md) and [License](assets/Licence.md).

## Masked native preparation (dev28 candidate)

Runtime calibration profiles can prepare only requested dials through the additive ABI 2 `aiedge_prepare_profile_masked` entry point. Alignment still runs for every frame. Selected dials retain the same crop, quality and radial-feature path; omitted rows remain unavailable and their caches are invalidated. Returning to a full observation rebuilds omitted features. The matching library is required for this optimized runtime-profile path; an older library explicitly rejects masked preparation. Default FULL uses the existing API.

The development event-selection CLI remains available alongside the explicit Home Assistant option. Default FULL recognition and configured fixed capture cadence remain. Disabling exact-region reuse conservatively uses full non-reuse preparation before applying the model mask. Built-in fixed profiles also retain full preparation. No stable-camera assumption, alignment bypass, automatic scheduling or camera transmission change is introduced.

Local evidence: one 27-frame clip gave exact selected native features/state/visibility and full-path parity. Masked native wrapper time was 0.246s versus baseline full 0.413s in one Windows-host sequence; this excludes decode/models/acquisition and is not an installed or sustained performance benchmark. The Reader disable-reuse fix has synthetic validation; no new real-model pass was run for that revision. Physical accuracy and cumulative consumption remain unverified.
