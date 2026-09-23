# AIEdge web installer

The public site is https://isentropik.github.io/AIEdge/ . It uses ESP Web Tools 10.4.0 for USB flashing and Improv Serial for Wi-Fi setup in the same browser. AIEdge's page and styling are original; third-party credits and license links appear on the page.

Only the explicit static-site files are published to the separate `codex/aiedge-site` branch. GitHub Pages serves that branch over HTTPS. Source history, dependencies and local working files are not copied into the website.

The manifest serves one ESP32 image at address 0. It is generated with esptool `merge_bin` using the release's bootloader at 0x1000, partition table at 0x8000, initial OTA selection at 0xd000, and loader at 0x10000, with DIO / 40 MHz / 4 MB flash settings. The first-install image replaces internal settings. It does not format the SD card.

`integrity.json` records source-file hashes and the merged image fingerprint. The browser verifies the merged bytes before exposing the USB button and passes those same bytes through an object URL to ESP Web Tools. A new release must update both JSON files and use a new immutable binary path. Never replace old release binaries silently.

The main package is still downloaded and verified by the board after Wi-Fi setup. Version 0.1.1's loader retains the pinned 0.1.0 application package; only the loader and browser installation flow change. The full provisioning flow remains hardware-unverified.
