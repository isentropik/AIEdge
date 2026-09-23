# Plain-language glossary

[Back to AIEdge](../README.md)

| Term | Meaning here |
| --- | --- |
| Firmware | The program running on the ESP32. |
| Flash / flashing | Flash is its internal storage; flashing means writing firmware to it. |
| Bootstrap / loader | The small installer that connects to Wi-Fi and installs the main program. |
| Bootloader | The lower-level startup program, separate from the AIEdge Wi-Fi loader. |
| Partition | A section of internal storage reserved for a particular purpose. |
| PSRAM | Extra working memory used for tasks such as image processing. |
| FAT32 | The storage format needed on the microSD card; different from exFAT. |
| COM / serial port | The computer's name for its connection to the programmer, such as COM8. |
| Download mode | The startup mode that allows USB firmware writing. |
| GPIO | A numbered connection pin on the board. |
| SSID | A Wi-Fi network's name. |
| AP | Access point: the temporary setup Wi-Fi network created by the board. |
| IP address | A device's numeric network address, usually assigned by your router. |
| mDNS / .local | Local name discovery, used to find aiedge.local without knowing its IP address. |
| DHCP | The router service that assigns network addresses. |
| DNS | The service that looks up Internet names such as github.com. |
| NTP | A way to obtain the correct time over a network. |
| HTTPS / TLS | The secure connection used to download from GitHub, including checks of the server's identity. |
| SHA-256 / hash / checksum | A file fingerprint used to check that a download matches the expected file. |
| Bundle / package | Matched firmware, website, model and supporting files. |
| OTA | Over-the-air updating through a network rather than USB. |
| Rollback | Returning to an earlier version after failure. Automatic rollback is not established for this preview. |
| ROI | Region of interest: the part of a picture selected for reading, such as one dial. |
| Alignment | Lining up new images with a reference using fixed features. |
| Calibration | Setting geometry and conversion values for the actual camera and meter. |
| Model / inference | The trained reading software / using it to estimate a reading from an image. |
| Polar reading | Estimating a needle's angular position around a calibrated center. |
| Rollover | A dial passing its highest number and continuing through zero. |
| MQTT broker | A messaging server that can pass readings to Home Assistant. |
| Prerelease | An early version intended for testing, with incomplete validation. |

You do not need to memorize these. Use this page when a guide or error uses an unfamiliar word.
