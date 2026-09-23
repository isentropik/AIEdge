# Development status

[Back to AIEdge](../README.md) · [Installation](INSTALLATION.md) · [Glossary](GLOSSARY.md)

**The release is ready for development testing, not yet proven as a complete installation on the board.** Passing a computer-based check does not prove a meter is read accurately or that a device will recover after a failed update.

In the table, the *loader* is the small Wi-Fi installer, *package integrity* means the files match their expected fingerprints, and *mDNS* is the name discovery used by `aiedge.local`.

| Check | Evidence / limitation |
| --- | --- |
| Main package | Clean ESP32 build and 73 completed local test scripts. These are not 73 hardware tests. |
| Package integrity | Production host stager verified 78 runtime files; full ZIP hash recorded. |
| Initial loader | Four flash regions hash-verified; board boot confirmed setup AP and mounted SD. |
| Initial transfer | Failed before receiving package bytes from the PC. Windows inbound blocking was suspected; no firewall change succeeded. |
| GitHub loader, mDNS, network picker | Compiled successfully for ESP32. Setup JavaScript syntax and package integrity checks pass. These changes are not yet flashed or verified end to end on hardware. |
| Accuracy | Limited human-labelled tests on one meter. Not coverage of every position, lighting or meter. Unlabelled predictions are not accuracy evidence. |
| Timing | Sustained valid-reading cadence and end-to-end duration on the target remain to be measured. |
| Recovery | Original board flash preserved; automatic bad-app/power-loss rollback unproven. |
| UI | Initial branding/style implemented; full mobile/device rendering verification incomplete. |

See the implementation notes for detailed limitations. Do not replace invalid or unknown readings with plausible-looking values.

## Browser installer and USB Wi-Fi (0.1.1)

The combined USB image has been checked against its four source files and flash addresses. Host tests cover Improv packet framing, checksum rejection, partial-input recovery, malformed credentials and scan-response formatting. The ESP32 loader compiles successfully. These are local checks; they do not establish successful browser flashing, live network scanning or credential handling on the physical board.
