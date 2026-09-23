# AIEdge

**Read an analog meter with a small camera and an ESP32.**

AIEdge takes pictures of a meter, estimates where its needles point, and can send readings to Home Assistant. Once installed, readings are processed on the device rather than sent to an online AI service.

**Built on [AI-on-the-edge-device](https://github.com/jomjol/AI-on-the-edge-device), created by jomjol and its contributors.** Their firmware, camera and meter-reading work provide the foundation. AIEdge is an independent modified fork, not an entirely new implementation or an official upstream release. See [credits](CREDITS.md).

> **Early development release:** the new GitHub installer has been built but still needs complete testing on the board. The included new needle-reading model was developed for one particular meter. Installing it does not make it ready to read every meter accurately. See [what has been tested](docs/STATUS.md).

## Start here

| What do you want to do? | Guide |
| --- | --- |
| Install AIEdge for the first time | [Step-by-step installation](docs/INSTALLATION.md) |
| Set up the camera and meter readings | [First-time configuration](docs/CONFIGURATION.md) |
| Fix a connection or installation problem | [Troubleshooting](docs/RECOVERY.md) |
| Understand an unfamiliar word | [Plain-language glossary](docs/GLOSSARY.md) |
| Download the installer | [Development releases](https://github.com/isentropik/AIEdge/releases) |
| Change or build the software | [Developer guide](docs/DEVELOPMENT.md) |

## What you need

- A supported **AI-Thinker-style ESP32-CAM** with **4 MB flash** and working **PSRAM**. These are the board's storage and extra memory; check its specifications. Other ESP32 variants are not verified by this release.
- A compatible camera and stable power supply.
- A **microSD card formatted as FAT32**. It stores the website, reading model and settings, and stays inserted during use.
- A compatible USB programming base or adapter, a data-capable USB cable, and a computer. A bare ESP32-CAM cannot connect directly to USB by itself.
- Home **2.4 GHz Wi-Fi**, its password, and Internet access for installation.
- A phone or computer with a web browser.

## How installation works

1. **Open the [web installer](https://isentropik.github.io/AIEdge/) in desktop Chrome or Edge.** Connect your supported board over USB and follow the install dialog.
2. **Choose Wi-Fi in the same dialog.** Select your home 2.4 GHz network and enter its password. Details go to the board over USB; no phone or network switching is required.
3. **Wait for the full installation.** The board downloads and verifies the main package. Keep power connected; use **Visit Device** to see progress.
4. **Open AIEdge.** After it restarts, visit **http://aiedge.local** and follow the [configuration guide](docs/CONFIGURATION.md).

No manual file downloads or terminal commands are needed for the browser method. The [installation guide](docs/INSTALLATION.md) also explains manual USB installation and the optional setup-hotspot fallback.

## What AIEdge changes

The underlying camera, meter-reading, web interface and integration foundations come from upstream. Work in this fork includes:

| Area | AIEdge additions and changes |
| --- | --- |
| Installation | A small USB loader followed by a checked GitHub package download. |
| Setup | A nearby Wi-Fi network list, rescan and manual entry. |
| Lighting | External LED brightness control and RGBW handling with a separate white channel. |
| Dial reading | A perspective-aware polar reading pipeline with meter-specific calibration. |
| Consumption | Secondary-wheel calculations and checks for contradictory or uncertain readings. |
| Updates | Matching firmware, website and model files kept together in a checked package. |
| Operations | Additional diagnostics, configuration activation tracking and optional image uploads. |
| Interface | AIEdge branding and initial style changes; some pages remain inherited and need more work. |

Implementation does not mean every feature has been verified on hardware. Read the [status page](docs/STATUS.md) before relying on this preview.

## Help

Start with [troubleshooting](docs/RECOVERY.md). When reporting a problem, include the board type, AIEdge version, exact error and what you tried. Remove passwords and private information first. See [contributing](CONTRIBUTING.md).

## Credits and license

Thanks to jomjol and the [AI-on-the-edge-device contributors](https://github.com/jomjol/AI-on-the-edge-device/graphs/contributors), Espressif and the other component authors. Their work remains credited in the source, [credits page](CREDITS.md) and [third-party notices](third-party-notices). Upstream authors do not provide or endorse this modified firmware.

The unchanged [upstream Dual Use License](Licence.md) applies. It permits private, non-commercial use under its terms; commercial use requires a separate license from the rights holder. This fork is not MIT- or GPL-licensed.
