# AIEdge Wi-Fi bootstrap

**Installing for the first time?** Use the [step-by-step installation guide](../docs/INSTALLATION.md). The notes below explain how the loader works internally and are intended for developers.

USB installs the loader. It starts AIEdge-Setup (WPA2 password AIEdgeSetup), advertises http://aiedge.local and provides http://192.168.4.1 as the setup fallback. A mobile-sized page scans 2.4 GHz networks, supports rescanning and manual entry, and can show the entered password.

The next build downloads an immutable GitHub release asset over HTTPS. NTP sets the clock, certificates are checked, and redirects are limited to the GitHub release hosts. The exact URL, size, SHA-256, bundle ID and model identity are compiled into src/package_pin.h. No PC server is required for this version.

The production stager verifies the ZIP and runtime assets. Firmware goes to the inactive OTA slot, is checked by SDK digest, and receives its verified SD bundle index before boot selection. First configuration uses SetupMode, hostname aiedge, LED intensity zero and no automatic recognition or uploads.

No SD formatting, camera access, training or production HA work occurs in the loader. Partial staging failures are preserved. The previous OTA slot is retained but automatic boot rollback is not enabled. Some failures require serial diagnosis/recovery. Keep power and the SD card connected during installation.

The first on-device loader used a PC URL and reached Wi-Fi but failed to download. GitHub, scanning and setup mDNS are prepared for the next flash; successful compilation does not prove end-to-end hardware installation.

## USB Wi-Fi provisioning (0.1.1 loader)

The loader now implements Improv Serial on UART0 at 115200 baud: state, device info, Wi-Fi scan, credential submission and the connected device URL. ESP Web Tools can configure Wi-Fi in its existing USB dialog. Binary packets use the UART driver directly; Wi-Fi credentials are not printed. HTTP and USB provisioning share validation and a serialized start operation.

A successful Wi-Fi response means the network is connected, not that package installation has completed. Visit the returned local address for progress. This service belongs to the loader, not the subsequently installed main application. The hotspot remains available as a fallback.

Host protocol tests: compile `tests/improv_test.cpp` with a C++11 compiler and `src` as an include directory, then run the result. Device provisioning, bad-password recovery, USB reset behavior and complete package installation still require hardware testing.

## Saved Wi-Fi and recovery (0.1.2 loader)

After a successful Wi-Fi connection, the loader commits the credentials to internal nonvolatile storage and verifies them before downloading the package. A reset or power interruption can then reconnect automatically, even if the package download previously failed. Invalid or unsuccessful connection attempts do not replace the last verified saved network. A fresh USB installation or erase can remove these settings; reconnecting alone should not.

Visit Device shows connection and installation status. If Wi-Fi is connected but the package fails, use **Retry download and installation** without reentering the network password. Download diagnostics report error codes or byte counts, never passwords or signed download URLs. The main application still receives its own SD-backed Wi-Fi configuration during installation.

The loader and installed device pages have a **Theme** selector: System, Light or Dark. The choice is saved in that browser for the device address. Images and calibration canvases are not recolored.

Validation: firmware compilation, host persistence tests (restart, malformed records, failed replacement save and unchanged-credential write avoidance), local package staging and browser theme/retry presentation checks passed. The reported device download failure still needs its detailed device-side error; this release does not claim the download root cause is resolved. Full hardware installation and reconnect testing remain necessary.

## Unique hostname and GitHub download fix (0.1.3 loader)

The default hostname is `aiedge-xxxxxx`, using the last three bytes of the Wi-Fi station MAC address in lowercase hexadecimal. DHCP, mDNS and the generated SD Wi-Fi configuration all use that same name. For example, `20:9b:a9:74:4b:20` becomes `aiedge-744b20.local`. The setup page shows the board's address. The setup hotspot name remains AIEdge-Setup.

The downloader now sizes its HTTP transmit buffer for the full bounded redirect URL plus the request-line overhead. The ESP-IDF default was 512 bytes; an observed GitHub release redirect required an 890-byte request line. This fixes a verified source-level failure before downloading any package bytes. TLS verification, allowed redirect hosts, byte count and SHA-256 checks remain enforced. Complete hardware download validation remains pending.

This loader continues to use the immutable 0.1.2 application package. The new interface redesign remains a separate local preview. Existing SD Wi-Fi files are not silently overwritten; a mismatch stops installation for review.

Version 0.1.4 carries the generated hostname into both wlan.ini and the System section of the initial config.ini, preventing a reset to the old generic name on application startup. Existing configurations remain protected.
