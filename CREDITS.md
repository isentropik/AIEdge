# Credits and project origins

[Back to AIEdge](README.md)

## The original project

AIEdge is a modified fork of **[AI-on-the-edge-device](https://github.com/jomjol/AI-on-the-edge-device)** by **[jomjol](https://github.com/jomjol)** and its [contributors](https://github.com/jomjol/AI-on-the-edge-device/graphs/contributors).

The original project supplies the firmware foundation, camera and image-processing infrastructure, meter recognition, web configuration, SD-card handling and integration capabilities that this fork builds on. These are not presented as original AIEdge inventions.

The initial AIEdge application is based on upstream revision [`a1ccda2`](https://github.com/jomjol/AI-on-the-edge-device/tree/a1ccda2e88f8924d6633b285f7b3334f3263cc2f), associated with version 16.1.0. The [original README at that revision](https://github.com/jomjol/AI-on-the-edge-device/blob/a1ccda2e88f8924d6633b285f7b3334f3263cc2f/README.md) preserves upstream context. The [upstream documentation](https://jomjol.github.io/AI-on-the-edge-device-docs/) describes that project; it is not a guarantee of this fork's behavior.

## AIEdge changes

This fork adds or modifies the polar analog-reading pipeline, secondary-wheel accounting, RGBW lighting and brightness controls, configuration activation, optional image uploads, diagnostics, matched update packages, Wi-Fi installer and interface styling. These changes build on inherited code; listing a feature here does not claim its entire implementation was created from scratch.

The [status page](docs/STATUS.md) distinguishes local checks from outstanding device validation. AIEdge is independent and is not endorsed or supported by the original authors.

## Other contributors and components

Thanks also to Espressif for the ESP32 platform and software, and to the authors of the other libraries and tools included in the source. Their individual copyright and license notices remain in their files, dependency repositories and [third-party notices](third-party-notices). Git history retains the original project history and authorship.

## License and visual material

The original [Dual Use License](Licence.md) is retained unchanged, along with third-party notices. Read those terms before using or redistributing this software; commercial use requires a separate license from the rights holder.

AIEdge's presentation documentation is written for this fork. Its README does not reuse upstream promotional images, screenshots or logos. Future presentation visuals should be original AIEdge screenshots or purpose-made diagrams, with illustrations clearly distinguished from actual device results. Inherited source assets retain their original provenance; changing the product name does not make them original AIEdge work.

## Browser installer and USB Wi-Fi

The browser installer uses [ESP Web Tools](https://github.com/esphome/esp-web-tools), by ESPHome / Open Home Foundation, under its [Apache-2.0 license](https://github.com/esphome/esp-web-tools/blob/10.4.0/LICENSE). It is loaded as a version-pinned component; browser flashing itself is their work.

AIEdge's loader implements the public [Improv Wi-Fi serial protocol](https://www.improv-wifi.com/serial/), an ESPHome and Home Assistant initiative funded by Nabu Casa. The AIEdge-specific installer page, checks and protocol adapter are separate additions. This credit does not imply endorsement by those projects.
