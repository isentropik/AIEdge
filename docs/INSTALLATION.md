# Install AIEdge for the first time

[Back to AIEdge](../README.md) · [Troubleshooting](RECOVERY.md) · [Glossary](GLOSSARY.md)

First, use a computer and USB cable to put a small installer on the board. Then use your phone to connect it to home Wi-Fi. It downloads the rest of AIEdge from GitHub.

> This development preview targets a classic AI-Thinker-style ESP32-CAM with 4 MB flash and working PSRAM. The GitHub loader has been compiled but has not yet passed a complete hardware installation test. Do not assume it works on another ESP32 variant.

## 1. Prepare the board and SD card

- Use a microSD card formatted as **FAT32**, not exFAT. Formatting erases it, so copy anything you need first. AIEdge does not format the card for you.
- Insert the card with the power off. Leave it inserted during setup and normal use.
- Use a compatible USB programming base or adapter and a **data-capable** cable. Some cables only supply power.
- If the board already runs something you want to keep, save its firmware and SD files before installing. Installation replaces firmware and the internal storage layout. A firmware backup does not include the SD card.

Follow your exact board and adapter's wiring instructions. Pin connections are not interchangeable between all ESP32-CAM programmers.

## 2. Download the files

Open [AIEdge releases](https://github.com/isentropik/AIEdge/releases), choose the development release and expand **Assets**. Put these five files together in a folder, such as `Downloads\AIEdge`:

| File | Purpose |
| --- | --- |
| `bootloader.bin` | Starts the board's software. |
| `partitions.bin` | Describes where its programs belong. |
| `ota_data_initial.bin` | Selects the initial program to start. |
| `aiedge-bootstrap.bin` | The small Wi-Fi installer. |
| `SHA256SUMS.txt` | File fingerprints for checking the downloads. |

Use files from the **same release**, without renaming them. Source-code ZIPs are for developers. You do not write `aiedge-package.zip` over USB: the Wi-Fi installer downloads that package itself.

### Check the downloads on Windows

Open the download folder in File Explorer, type `powershell` in its address bar and press Enter. This opens a command window in that folder.

Run this read-only check:

```powershell
Get-FileHash -Algorithm SHA256 bootloader.bin, partitions.bin, ota_data_initial.bin, aiedge-bootstrap.bin
```

Open `SHA256SUMS.txt` and compare the long code for each of those four filenames. Uppercase and lowercase letters are equivalent. Every code must match. If one differs, download that file again before continuing.

## 3. Install the USB writing tool

**esptool** writes firmware to an ESP32. These instructions use Windows PowerShell and esptool version 4.

Install Python 3 from [python.org](https://www.python.org/downloads/) if needed, then open a new PowerShell window. Run:

```powershell
py --version
py -m pip install "esptool>=4,<5"
```

If `py` is not recognized but `python --version` works, use `python` instead of `py` throughout this guide. If neither works, finish installing Python and reopen PowerShell.

On macOS or Linux, the Python command and serial-port name differ. The file addresses below still apply only to the supported board and flash set.

## 4. Find the USB port

1. Open Windows **Device Manager** and expand **Ports (COM & LPT)**.
2. Connect the board through its USB programmer. Note the port that appears, such as `COM8`.
3. If unsure, unplug and reconnect once and watch which entry disappears and returns. Do this before starting a firmware write.

If no port appears, check the data cable and your adapter manufacturer's driver. Port numbers can change; `COM8` is only an example. Close any serial-monitor program using the port.

## 5. Write the installer

Put the board in **download mode**, which allows USB firmware writing. Some USB bases do this automatically. Many ESP32-CAM boards require GPIO0 connected to GND during reset; follow your programmer's instructions.

In PowerShell, open the folder with the downloaded files as described above. Replace `YOUR_PORT` with the port you identified, then run this as one line:

```powershell
py -m esptool --chip esp32 --port YOUR_PORT --baud 460800 write_flash --flash_mode dio --flash_freq 40m --flash_size 4MB 0x1000 bootloader.bin 0x8000 partitions.bin 0xd000 ota_data_initial.bin 0x10000 aiedge-bootstrap.bin
```

For example, `--port YOUR_PORT` becomes `--port COM8`. Leave the other values unchanged for this release and supported board.

**What you should see:** esptool connects, writes all four files and verifies the data. Do not disconnect power during the write. If it reports an error, use [troubleshooting](RECOVERY.md) before continuing.

After success, remove the GPIO0-to-GND connection if you used one, then reset or power-cycle the board. Leaving that connection in place keeps it in download mode instead of starting AIEdge.

## 6. Connect your phone

1. Join **AIEdge-Setup** in your phone's Wi-Fi settings.
2. Enter **AIEdgeSetup**. This is the setup-network password, not your home Wi-Fi password.
3. If warned that this network has **no Internet**, choose to stay connected. That is expected.
4. Enter **http://aiedge.local** in the browser's address bar. If it fails, use **http://192.168.4.1**. Include `http://` rather than searching for the name.

**What you should see:** an AIEdge page with a Wi-Fi list, password field and **Connect and install** button.

## 7. Select home Wi-Fi and install

1. Choose your network. Use **Rescan networks** if needed, or **Hidden network / enter manually** to type a hidden network's name.
2. Enter its password. **Show password** lets you check it.
3. Press **Connect and install** once. Keep power connected and stay on **AIEdge-Setup** while installation runs.

| Status text | Meaning |
| --- | --- |
| Connecting to Wi-Fi | Joining home Wi-Fi. |
| Setting the clock for secure download | Getting the time to check GitHub's security certificate. |
| Downloading AIEdge | Fetching the package. |
| Verifying package and SD files | Checking the download and files saved to the card. |
| Installing verified firmware | Writing the main program. Keep power connected. |
| Installed. Restarting; reconnect to your home Wi-Fi | Installation has reached the restart step. Rejoin home Wi-Fi. |

The bar measures the **download**, not the whole installation. It can reach 100% before verification and installation finish. The setup page can disconnect during the final restart.

Use **2.4 GHz Wi-Fi**. A shared 2.4/5 GHz name can work if the router offers compatible 2.4 GHz access. Enterprise logins and WPA3-only networks are unsupported. No PC server or router port forwarding is needed.

Less common limits: network names are limited to 31 UTF-8 bytes and passwords to 63 bytes; quotes and line breaks are unsupported. Ordinary English characters each use one byte; some other characters use more. Password-protected networks need at least eight password characters. Open networks must appear in the scan list; hidden open networks are unsupported.

## 8. Open the main website

Reconnect your phone to home Wi-Fi and open **http://aiedge.local**.

If needed, find **aiedge** in your router's connected-device list and use its IP address. For example, `http://192.168.1.50` is the form of address to enter, but use the actual number from your router.

**Installation is complete when the main AIEdge website opens.** The meter is not calibrated yet. Continue to [first-time configuration](CONFIGURATION.md).

## Older loaders and later updates

If your current loader says **Package download failed; check the PC server**, it cannot change to GitHub downloads through its webpage. Install the newer USB loader using this guide.

For later updates, use the main website's managed update feature with a compatible **complete AIEdge package** and that release's instructions. Firmware, website and model files must stay matched; an unrelated app binary is insufficient. Keep USB recovery available: automatic recovery after a failed startup or interrupted update has not been established for this preview.
