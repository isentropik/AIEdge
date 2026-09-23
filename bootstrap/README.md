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

Visit Device shows connection and installation status. If Wi-Fi is connected but the package fails, use **Retry download to device and install** without reentering the network password. Download diagnostics report error codes or byte counts, never passwords or signed download URLs. The main application still receives its own SD-backed Wi-Fi configuration during installation.

The loader and installed device pages have a **Theme** selector: System, Light or Dark. The choice is saved in that browser for the device address. Images and calibration canvases are not recolored.

Validation: firmware compilation, host persistence tests (restart, malformed records, failed replacement save and unchanged-credential write avoidance), local package staging and browser theme/retry presentation checks passed. The reported device download failure still needs its detailed device-side error; this release does not claim the download root cause is resolved. Full hardware installation and reconnect testing remain necessary.

## Unique hostname and GitHub download fix (0.1.3 loader)

The default hostname is `aiedge-xxxxxx`, using the last three bytes of the Wi-Fi station MAC address in lowercase hexadecimal. DHCP, mDNS and the generated SD Wi-Fi configuration all use that same name. For example, `20:9b:a9:74:4b:20` becomes `aiedge-744b20.local`. The setup page shows the board's address. The setup hotspot name remains AIEdge-Setup.

The downloader now sizes its HTTP transmit buffer for the full bounded redirect URL plus the request-line overhead. The ESP-IDF default was 512 bytes; an observed GitHub release redirect required an 890-byte request line. This fixes a verified source-level failure before downloading any package bytes. TLS verification, allowed redirect hosts, byte count and SHA-256 checks remain enforced. Complete hardware download validation remains pending.

This loader continues to use the immutable 0.1.2 application package. The new interface redesign remains a separate local preview. Existing SD Wi-Fi files are not silently overwritten; a mismatch stops installation for review.

Version 0.1.4 carries the generated hostname into both wlan.ini and the System section of the initial config.ini, preventing a reset to the old generic name on application startup. Existing configurations remain protected.

## Download progress and slow-connection handling (0.1.5 loader)

The setup page shows downloaded and total bytes, percentage, average download speed and estimated time remaining. The estimate starts after three seconds of transfer and disappears if no data arrives for ten seconds, the connection is lost, or the download fails. Transfer completion is followed by separate verification and installation stages; 100% downloaded does not mean installation is complete.

The former two-minute transfer limit stopped a real download before it finished. The loader now permits up to ten minutes for the body transfer, with a separate thirty-second no-data limit. A temporary read timeout continues the same verified transfer; it does not skip bytes or restart the hash. Terminal connection errors and all size/SHA-256 checks still stop installation. Individual socket reads have a ten-second timeout, so deadline handling occurs at the next bounded read boundary.

The HTTP server now evicts idle browser connections and reserves sockets for the downloader and name lookup. Setup requests time out visibly and retry instead of leaving a stale speed estimate; setup/status responses are not cached. This addresses a source-level connection-capacity problem, but the user's initial blank page and mDNS failure are not yet proven fixed on hardware. USB diagnostics confirmed loader 0.1.4 and the intended hostname while IP HTTP and mDNS lookups failed; the board still answered ping. Version 0.1.5 prints the mDNS initialization result after UART setup to support further diagnosis.

The USB browser installer also gains a Show password eye button. It requires a website refresh, not a firmware reflash. Download display and timeout changes are firmware changes and require updating the loader. The underlying application package remains the immutable 0.1.2 package.

## Start installation when ready (0.1.6 loader)

Connecting Wi-Fi now stops at **Ready to download to device and install**. Choose **Visit Device**, then **Download to device and install** when ready. This also applies after restarting with saved Wi-Fi. Opening or refreshing the page never starts the download. Failed installation attempts offer a separate retry button; requests during an active installation are rejected.

Package hashing yields periodically so lower-priority system tasks can run. The page and USB log report SD verification, unpacking, initial configuration, firmware writing and startup preparation separately. All package and file hashes remain enforced. These changes improve diagnostics and scheduling; they do not establish the cause or resolution of the reported post-download lockup. Loader 0.1.5 reported successful mDNS initialization, but hostname reachability remains unverified.

Validation: firmware build, saved-Wi-Fi tests, connected/reboot consent gates, failed connection/save paths, SHA-256 equivalence across different chunk sizes and browser consent behavior passed. Hardware installation and recovery testing remain necessary. The main application package is unchanged.

## Installation debug log (0.1.7 loader)

Choose **Download debug log** on the device setup page to save a text file. It contains the most recent 96 diagnostic entries from the current boot: elapsed milliseconds, loader version, reset reason, available memory, and the operation/file offset being processed. It does not include Wi-Fi credentials, network names or signed package URLs.

Read-back verification records file open/read, hashing and completion checkpoints. Unpacking and firmware writing have their own checkpoints. Block-level messages are sampled every 64 KiB; a separate task reports the current operation and its age every ten seconds during installation. These heartbeat messages can help distinguish a slow operation from one that has stopped progressing.

The log is held in bounded RAM and also sent over USB at 115,200 baud. It does not write to the SD card, because an SD fault could also block a log stored there. RAM history clears after restart, and a stopped web server cannot serve the download. For a lockup test, open USB **Logs & Console** before starting the package download and save that log afterward. Only one program can own the USB port at a time.

The diagnostic loader preserves explicit download consent, package verification and the pinned application package. A debug log is evidence, not a lockup fix. Host tests cover bounded log retention, timestamps, actual verifier checkpoints, corrupt and missing files, and the existing staging/recovery checks. Hardware diagnosis remains pending.

## Wi-Fi scanning while ready (0.1.8 loader)

The ready-to-install state allows scanning and changing Wi-Fi. Active connection and installation stages remain protected. Disconnected ready devices report ready for setup over USB, rather than connecting. Failed, cancelled, refused or timed-out scans return an Improv error; only a completed scan sends a successful network list, which may genuinely be empty. A timed-out scan is stopped so another scan can be attempted. Scan failures are recorded in the current-boot debug log without network names or credentials.

Host tests exercise the actual scan and reply code for ready/busy states, driver failure, timeout, cancellation, empty success, deduplication and network results. Physical network discovery remains to be verified after updating the loader. This release does not establish a fix for the separate package-installation lockup.

## ZIP extraction stack fix (0.1.9 loader)

A recorded test passed package download and SD read-back verification, then reported a stack overflow in the download task as ZIP unpacking began. ZIP opening also nests two 4 KiB stack buffers. The installer now allocates its firmware-transfer buffer on the heap, reducing its own compiled stack frame from 4,768 to 704 bytes. Extraction uses the heap-backed miniz iterator instead of the large-stack convenience functions, with bounded 4 KiB transfers and checked completion. CRC, length limits and SHA verification remain required. The debug log includes minimum remaining task stack space.

The corrected loader completed a recorded hardware installation: package download, all SD file checks, firmware write and reboot. The minimum reported installation-task stack space at completion was 2,368 bytes. The application then exposed a separate startup crash in the ESP32 hardware SHA digest routine. The 0.1.9 application package uses mbedTLS software SHA-256; integrity checks remain mandatory. Its model and web assets are unchanged. Full application-startup validation is still pending.

The build passes 72 verification/staging/recovery cases, and all 80 installable files from the new package match after host extraction. The setup page now probes the application's system-information endpoint when loader status disappears, and automatically opens the application when it responds. Offline and invalid responses keep retrying. The device action is labeled **Download to device and install**. An unformatted or unsupported SD card prevents setup; it is never formatted automatically.
