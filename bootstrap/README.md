# AIEdge Wi-Fi bootstrap

USB installs the loader. It starts AIEdge-Setup (WPA2 password AIEdgeSetup), advertises http://aiedge.local and provides http://192.168.4.1 as the setup fallback. A mobile-sized page scans 2.4 GHz networks, supports rescanning and manual entry, and can show the entered password.

The next build downloads an immutable GitHub release asset over HTTPS. NTP sets the clock, certificates are checked, and redirects are limited to the GitHub release hosts. The exact URL, size, SHA-256, bundle ID and model identity are compiled into src/package_pin.h. No PC server is required for this version.

The production stager verifies the ZIP and runtime assets. Firmware goes to the inactive OTA slot, is checked by SDK digest, and receives its verified SD bundle index before boot selection. First configuration uses SetupMode, hostname aiedge, LED intensity zero and no automatic recognition or uploads.

No SD formatting, camera access, training or production HA work occurs in the loader. Partial staging failures are preserved. The previous OTA slot is retained but automatic boot rollback is not enabled. Some failures require serial diagnosis/recovery. Keep power and the SD card connected during installation.

The first on-device loader used a PC URL and reached Wi-Fi but failed to download. GitHub, scanning and setup mDNS are prepared for the next flash; successful compilation does not prove end-to-end hardware installation.
