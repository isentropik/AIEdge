# AIEdge

**Experimental ESP32-CAM firmware for reading analog meters locally.**

AIEdge is a modified fork of [AI-on-the-edge-device](https://github.com/jomjol/AI-on-the-edge-device), focused on analog dial recognition, controllable lighting, clearer diagnostics, and simpler installation. Recognition runs on the device; Internet access is needed for the GitHub installer, not for every reading.

> **Development preview.** The included polar model and geometry are specific to the development meter. Accurate readings on another meter require calibration and independent validation. The upstream authors do not provide or endorse this modified firmware.

[Installation](docs/INSTALLATION.md) · [Configuration](docs/CONFIGURATION.md) · [Recovery](docs/RECOVERY.md) · [Build instructions](docs/DEVELOPMENT.md) · [Validation status](docs/STATUS.md) · [Releases](https://github.com/isentropik/AIEdge/releases)

## What changes

| Area | AIEdge work |
| --- | --- |
| Installation | USB Wi-Fi loader, then a hash-pinned package download to SD and the inactive firmware slot. |
| Setup | Nearby 2.4 GHz network selection, rescan, hidden-network entry, password visibility, and `aiedge.local`. |
| Lighting | External LED master intensity and RGBW handling with a dedicated white channel. |
| Recognition | Perspective-aware polar dial pipeline, fixed calibration identities, and explicit invalid/unknown outcomes. Upstream numeral support remains present. |
| Consumption | Rollover-aware cumulative accounting and secondary-wheel reconciliation; ambiguous missing rotations are not invented. |
| Updates | Firmware and matching SD assets are verified together. An app binary alone is not a complete managed update. |
| Operations | Cycle diagnostics, coordinated camera access, configuration activation tracking, and optional image archival. |
| Interface | AIEdge branding and a first shared visual refresh. Some inherited pages still need further mobile work. |

Implementation does not imply hardware validation. See the [status table](docs/STATUS.md) for evidence and outstanding checks.

## Hardware

The development target is a classic AI-Thinker-style **ESP32-CAM**, with **4 MB flash**, working PSRAM, a supported camera, and a **FAT32 microSD card**. USB/serial access is required for the first flash and recovery. This release does not establish ESP32-S3, C3 or other-board compatibility.

The SD card holds the web interface, model, bundle metadata and configuration. The loader does not format it automatically. Use a compatible 2.4 GHz personal Wi-Fi network; enterprise authentication is not implemented by the setup page.

## Quick start

1. Read the release notes and [installation guide](docs/INSTALLATION.md). Download the matched AIEdge installer flash set.
2. Flash the loader over USB and leave a formatted microSD card inserted.
3. On your phone, join **AIEdge-Setup**, password **AIEdgeSetup**.
4. Open **http://aiedge.local**, or **http://192.168.4.1** if name discovery is unavailable.
5. Select home Wi-Fi and choose **Connect and install**. Keep power connected during download, verification and installation.
6. Rejoin home Wi-Fi and open **http://aiedge.local**. Complete camera, lighting, meter and integration configuration before enabling recognition.

The older local-server loader requires the IP address and cannot switch itself to GitHub downloads. Reflash the newer loader first. See [recovery](docs/RECOVERY.md).

## Development

Initial firmware source is pinned to upstream commit `a1ccda2e88f8924d6633b285f7b3334f3263cc2f` (16.1.0), with AIEdge modifications. Use a recursive checkout and the documented tool versions. An arbitrary upstream `main` build is not equivalent to an AIEdge release.

Include board/release version, reproduction steps and redacted diagnostics in reports. Never publish credentials, complete flash backups or private meter images. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License and attribution

The unchanged [upstream Dual Use License](Licence.md) applies: private, non-commercial use is permitted under its terms; commercial use requires the rights holder's separate license. This fork is not MIT- or GPL-licensed. Third-party components retain their own licenses. See [third-party notices](third-party-notices) and the original [upstream README](README.upstream.md).

Thanks to jomjol and the AI-on-the-edge-device contributors, Espressif, and the other component authors. AIEdge is an independent modified version.
