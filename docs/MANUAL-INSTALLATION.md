# Manual installation (optional)

The [web installer](https://isentropik.github.io/AIEdge/) is recommended. Use this guide only if you cannot use a supported browser or prefer command-line tools.

Use a supported classic ESP32-CAM with 4 MB flash, working PSRAM, a compatible USB programmer and an inserted FAT32 microSD card. Save anything you need before replacing firmware or internal settings. This procedure does not format the SD card.

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

After flashing, follow the [web installer's Wi-Fi instructions](https://isentropik.github.io/AIEdge/), including its hotspot fallback if needed.

## Wi-Fi compatibility

Use compatible **2.4 GHz Wi-Fi**, such as WPA2-Personal. A shared 2.4/5 GHz name can work if the router offers a compatible 2.4 GHz connection. Enterprise logins and WPA3-only networks are unsupported. No PC download server or port forwarding is needed.

Network names are limited to 31 UTF-8 bytes and passwords to 63 bytes; quotes and line breaks are unsupported. Ordinary English characters each use one byte. Password-protected networks need at least eight password characters. The hotspot form cannot provision a manually entered hidden open network.

## Updating later

Use the main website's managed update feature with a compatible complete AIEdge package and that release's instructions. The firmware, website and model must stay matched. The first-install browser flasher is not a substitute for a settings-preserving update.

Keep USB recovery available. Automatic recovery from a failed boot or interrupted update is not established for this preview. See [troubleshooting and recovery](RECOVERY.md).
