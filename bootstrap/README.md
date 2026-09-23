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
