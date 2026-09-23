# Installation

## Prepare

Use an ESP32-CAM matching the release target, stable power, and FAT32 microSD. Save existing flash and SD contents if you need recovery. Flash backups do not include SD contents. The installer does not format storage or preserve unrelated partition layouts.

Download the installer files and SHA-256 checksums from one AIEdge prerelease. The app package ZIP is not a USB-flash image. Only use a release with a complete bootstrap flash set.

For the initial classic ESP32 4 MB layout, the flash set contains `bootloader.bin`, `partitions.bin`, `ota_data_initial.bin` and `aiedge-bootstrap.bin`:

```sh
python -m esptool --chip esp32 --port YOUR_PORT --baud 460800 write_flash --flash_mode dio --flash_freq 40m --flash_size 4MB 0x1000 bootloader.bin 0x8000 partitions.bin 0xd000 ota_data_initial.bin 0x10000 aiedge-bootstrap.bin
```

This uses esptool 4.x syntax. Verify checksums and the actual connected board before flashing; replace `YOUR_PORT`. COM numbers can change. Follow your programmer's boot-mode procedure, and release GPIO0 from ground before normal startup. Use offsets belonging to the exact flash set, not another board's layout.

## Phone setup

1. Join **AIEdge-Setup** with **AIEdgeSetup**. Stay connected if warned that the network has no Internet.
2. Open **http://aiedge.local**, with **http://192.168.4.1** as fallback.
3. Select a nearby network or use **Rescan** / **Hidden network / enter manually**. The ESP32 scans 2.4 GHz Wi-Fi; the webpage does not access your phone's native Wi-Fi settings.
4. Enter the password and choose **Connect and install**. The loader obtains time for TLS verification, downloads its pinned GitHub asset, and verifies the package and individual files.
5. It writes the app to the inactive OTA slot, verifies its identity and matching SD bundle, then restarts.
6. Rejoin home Wi-Fi and open **http://aiedge.local**. If needed, find hostname `aiedge` in the router's DHCP list and use that address.

Current limits: SSIDs up to 31 UTF-8 bytes, passwords up to 63 bytes, no quotes or line breaks. These reflect the inherited WLAN file format. Enterprise networks, hidden open networks and pure WPA3-only setup are not supported by this page. Unsupported scanned networks are labelled.

## Network and first run

The GitHub loader needs DNS, NTP and outbound HTTPS to GitHub and its release-asset hosts. It needs no PC server or router port forwarding. Clock-sync failure does not disable certificate verification.

The initial configuration uses hostname `aiedge`, SetupMode enabled and LED intensity zero. Automatic recognition stays off until configuration is completed. No personal WLAN, MQTT or archive credentials are distributed.

Set exposure, alignment markers, ROIs, dial directions, units and lighting before enabling processing. The included polar model is meter-specific. Compare readings with the physical meter before using them for cumulative consumption.

## Later updates

Use the managed update page with a compatible complete package. It binds application, HTML, model and diagnostics together. An app-only binary from another build is insufficient. Read migration notes, retain recovery access, and verify version and operation afterwards. Automatic recovery from bad firmware or power loss has not been established for this prerelease.
