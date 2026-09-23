# Install AIEdge from your browser

[Back to AIEdge](../README.md) · [Troubleshooting](RECOVERY.md) · [Glossary](GLOSSARY.md)

## Recommended: use the web installer

**The web installer is the preferred method for first-time installation.** Follow steps 1–4 below in desktop Chrome or Edge. You do not need to download firmware files manually, install Python or type terminal commands.

**[Start the recommended web installation →](https://isentropik.github.io/AIEdge/)**

Install the Wi-Fi loader and enter your home Wi-Fi details in the same desktop browser, over USB. Your computer stays connected to its usual network; a phone is not required.

The [manual USB instructions](#manual-usb-installation-alternative) farther down are an optional fallback. **Skip them when using the web installer.**

> Development preview: the USB Wi-Fi protocol passes local tests and the firmware builds, but the complete browser-to-board installation and provisioning still need hardware testing. This targets a classic AI-Thinker-style ESP32-CAM with 4 MB flash and working PSRAM, not arbitrary ESP32 boards.

## What you need before starting

- Use **desktop Chrome or Edge**, a compatible USB programming base/adapter and a data-capable USB cable. A bare ESP32-CAM cannot plug directly into USB.
- Insert a **FAT32 microSD card** with the power off. Leave it inserted; it stores the website, model and settings. AIEdge does not format it for you.
- Have your **2.4 GHz home Wi-Fi** name and password ready. Internet access is needed for the GitHub download.
- Installation replaces firmware and internal settings. Save anything you need first. A flash backup does not include the SD card, and formatting a card erases its contents.

## 1. Open the web installer

Open **[install AIEdge in your browser](https://isentropik.github.io/AIEdge/)** in desktop Chrome or Edge. Keep that page open for both installation and Wi-Fi setup.

**The web installer uses your USB cable to communicate with the board.** USB is the connection, not a separate manual installation method. The browser handles the firmware download and writing for you.

## 2. Connect the board and install from the webpage

1. Connect the board through its USB programmer. Close any serial-monitor program using that port.
2. Wait for the webpage to show **Installer files checked. Ready to connect.**
3. Click **Connect to ESP32**, choose the board's USB port and follow the browser's installation dialog. Read its erase/install confirmation before proceeding.
4. Keep power connected until the browser reports that the USB installation has finished.

Some programming bases enter download mode and reset automatically. Others need GPIO0 connected to GND during reset. Follow your exact board/adapter instructions. If you used that connection, remove it after flashing and reset to start the loader normally; then reconnect from the installer if necessary.

If no port appears, check the data cable and the adapter manufacturer's USB driver. On Windows, Device Manager's **Ports (COM & LPT)** list can identify the port by unplugging and reconnecting before starting a write.

## 3. Set up Wi-Fi in the web installer

Once the loader starts, ESP Web Tools detects its USB Wi-Fi setup service. Choose **Connect to Wi-Fi**, select your home network and enter its password. You can also enter a network manually when needed.

The password goes directly to the board over USB. You do not need to join AIEdge-Setup or switch your computer's network. The service uses the standard [Improv Wi-Fi serial protocol](https://www.improv-wifi.com/serial/).

If the Wi-Fi option is missing, check that the loader started normally and GPIO0 is no longer grounded. The older 0.1.0 loader does not support USB Wi-Fi provisioning; install the 0.1.1 loader or use the hotspot fallback below.

## 4. Wait for installation to finish, then open AIEdge

After Wi-Fi connects, the board downloads the main AIEdge package itself. **Wi-Fi connected does not mean the full installation is finished.** Keep USB power connected.

Choose **Visit Device** in the dialog to open the board's local address and see progress. Your computer must be able to reach the selected home network; a guest network may block this. The board checks the clock, downloads the package, verifies it and installs it before restarting. The download bar can reach 100% before verification and installation finish.

After the restart, open **http://aiedge.local**. If needed, find **aiedge** in your router's connected-device list and open its actual IP address instead.

Installation is complete when the main AIEdge website opens. Continue to [first-time configuration](CONFIGURATION.md). The reading model still needs appropriate calibration and validation for your meter.

The USB Wi-Fi service added in this release is in the installer. Do not assume it remains available in the main application after installation.

## Hotspot setup: optional fallback

If USB Wi-Fi setup is unavailable, a computer or phone can use the loader's hotspot:

1. Join **AIEdge-Setup**, password **AIEdgeSetup**. Stay connected if warned that it has no Internet.
2. Open **http://aiedge.local**, or **http://192.168.4.1** if needed.
3. Choose home Wi-Fi, enter its password and press **Connect and install**.
4. Keep power connected. Once it says it is restarting, reconnect to home Wi-Fi and open **http://aiedge.local** again.

This is an alternative, not an extra required step after USB provisioning.

## Wi-Fi compatibility

Use compatible **2.4 GHz Wi-Fi**, such as WPA2-Personal. A shared 2.4/5 GHz name can work if the router offers a compatible 2.4 GHz connection. Enterprise logins and WPA3-only networks are unsupported. No PC download server or port forwarding is needed.

Network names are limited to 31 UTF-8 bytes and passwords to 63 bytes; quotes and line breaks are unsupported. Ordinary English characters each use one byte. Password-protected networks need at least eight password characters. The hotspot form cannot provision a manually entered hidden open network.

## Manual USB installation alternative

**Optional fallback — not required for web installation.** The web installer above is recommended. Use these manual steps only if you cannot use a supported browser or specifically prefer command-line tools. After flashing, continue with either USB Wi-Fi setup above or the hotspot fallback.

<details>
<summary>Show optional manual downloads and command-line instructions</summary>

### Download the files

Open [AIEdge releases](https://github.com/isentropik/AIEdge/releases), choose the development release and expand **Assets**. Put these five files together in a folder, such as `Downloads\AIEdge`:

| File | Purpose |
| --- | --- |
| `bootloader.bin` | Starts the board's software. |
| `partitions.bin` | Describes where its programs belong. |
| `ota_data_initial.bin` | Selects the initial program to start. |
| `aiedge-bootstrap.bin` | The small Wi-Fi installer. |
| `SHA256SUMS.txt` | File fingerprints for checking the downloads. |

Use files from the **same release**, without renaming them. Source-code ZIPs are for developers. You do not write `aiedge-package.zip` over USB: the Wi-Fi installer downloads that package itself.

#### Check the downloads on Windows

Open the download folder in File Explorer, type `powershell` in its address bar and press Enter. This opens a command window in that folder.

Run this read-only check:

```powershell
Get-FileHash -Algorithm SHA256 bootloader.bin, partitions.bin, ota_data_initial.bin, aiedge-bootstrap.bin
```

Open `SHA256SUMS.txt` and compare the long code for each of those four filenames. Uppercase and lowercase letters are equivalent. Every code must match. If one differs, download that file again before continuing.

### Install the USB writing tool

**esptool** writes firmware to an ESP32. These instructions use Windows PowerShell and esptool version 4.

Install Python 3 from [python.org](https://www.python.org/downloads/) if needed, then open a new PowerShell window. Run:

```powershell
py --version
py -m pip install "esptool>=4,<5"
```

If `py` is not recognized but `python --version` works, use `python` instead of `py` throughout this guide. If neither works, finish installing Python and reopen PowerShell.

On macOS or Linux, the Python command and serial-port name differ. The file addresses below still apply only to the supported board and flash set.

### Find the USB port

1. Open Windows **Device Manager** and expand **Ports (COM & LPT)**.
2. Connect the board through its USB programmer. Note the port that appears, such as `COM8`.
3. If unsure, unplug and reconnect once and watch which entry disappears and returns. Do this before starting a firmware write.

If no port appears, check the data cable and your adapter manufacturer's driver. Port numbers can change; `COM8` is only an example. Close any serial-monitor program using the port.

### Write the installer

Put the board in **download mode**, which allows USB firmware writing. Some USB bases do this automatically. Many ESP32-CAM boards require GPIO0 connected to GND during reset; follow your programmer's instructions.

In PowerShell, open the folder with the downloaded files as described above. Replace `YOUR_PORT` with the port you identified, then run this as one line:

```powershell
py -m esptool --chip esp32 --port YOUR_PORT --baud 460800 write_flash --flash_mode dio --flash_freq 40m --flash_size 4MB 0x1000 bootloader.bin 0x8000 partitions.bin 0xd000 ota_data_initial.bin 0x10000 aiedge-bootstrap.bin
```

For example, `--port YOUR_PORT` becomes `--port COM8`. Leave the other values unchanged for this release and supported board.

**What you should see:** esptool connects, writes all four files and verifies the data. Do not disconnect power during the write. If it reports an error, use [troubleshooting](RECOVERY.md) before continuing.

After success, remove the GPIO0-to-GND connection if you used one, then reset or power-cycle the board. Leaving that connection in place keeps it in download mode instead of starting AIEdge.


</details>

## Updating later

Use the main website's managed update feature with a compatible complete AIEdge package and that release's instructions. The firmware, website and model must stay matched. The first-install browser flasher is not a substitute for a settings-preserving update.

Keep USB recovery available. Automatic recovery from a failed boot or interrupted update is not established for this preview. See [troubleshooting and recovery](RECOVERY.md).
