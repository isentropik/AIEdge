# Troubleshooting and recovery

[Back to AIEdge](../README.md) · [Installation](INSTALLATION.md) · [Glossary](GLOSSARY.md)

Start with your symptom below. Keep the exact error text. Do not disconnect power while firmware is being written or installed.

## The setup Wi-Fi network is missing

Check power and confirm USB installation succeeded. If you connected **GPIO0 to GND** for programming, remove that connection and reset the board after the write finishes. Otherwise it stays in download mode.

If setup already completed, look on home Wi-Fi instead. If the setup network never appeared, check the board model and installation output before writing again.

## aiedge.local will not open

- On **AIEdge-Setup**, use **http://192.168.4.1**.
- After installation, reconnect to **home Wi-Fi**, find **aiedge** in your router's connected-device list and open its listed IP address.
- Enter the full `http://` address, rather than searching or substituting `https://`.

The `.local` name uses automatic local discovery. Some phones and networks do not handle it reliably; the IP address avoids that step. A guest network may also prevent access between devices.

## The phone says there is no Internet

That is expected on **AIEdge-Setup**. Choose to stay connected. It connects your phone directly to the board; the AIEdge page lets you select home Wi-Fi next.

## Home Wi-Fi is missing or will not connect

Press **Rescan networks**, check the password with **Show password**, and move closer to the router if needed. Network names and passwords are case-sensitive.

The router must offer compatible **2.4 GHz Wi-Fi**, such as WPA2-Personal. A 5 GHz-only or WPA3-only network is unsupported. For a hidden password-protected network, choose **Hidden network / enter manually**. See [Wi-Fi compatibility](MANUAL-INSTALLATION.md#wi-fi-compatibility) for name and password limits.

## Setting the clock fails

Correct time is needed to check GitHub's security certificate. Check Internet access. On a restricted network, ask its administrator whether DNS, outbound HTTPS and network time (NTP) are allowed. Do not disable certificate checks to work around it.

## Download failed

Try downloading the package from the [release page](https://github.com/isentropik/AIEdge/releases) on a computer using the same home network. This helps check availability but does not prove the ESP32 has the same access. Check its Wi-Fi signal and exact error too.

If the message says **check the PC server**, this is the older local-server loader. It cannot switch to GitHub downloads through its webpage. Use the newer USB loader in [installation](INSTALLATION.md).

## The bar is at 100%, but setup is not finished

The bar measures download progress. Verification and installation happen afterwards. Follow the status text and keep power connected. Wait for the restart message before switching your phone back to home Wi-Fi.

## SD card cannot be opened

When no write is in progress, power off and check the card is seated. It must use **FAT32**, not exFAT. The installer does not format it automatically. Save anything you need before formatting; formatting erases the card. A failing card can also cause installation or verification errors.

## Verification failed or staging conflict

**Verification** checks that files match the expected download. **Staging** prepares them on the SD card before installation.

Keep the error and existing files. Do not bypass verification or delete partial folders at random. Check that the installer and package belong to the same release and that the card is healthy. Conflicting or interrupted files may be retained deliberately for diagnosis.

## The USB tool cannot connect

Check the COM port, close other programs using it, and follow download-mode instructions for the exact board and adapter. Try a known data cable. An example port such as `COM8` may not be yours.

If writing begins and then fails, keep the full output and resolve the error before trying normal startup.

## The main program will not start

This preview has **no proven automatic rollback**. A loader remaining in another flash slot does not mean the board will automatically return to it after a failure.

USB recovery may be necessary. After preserving settings or evidence you need, use the complete matched installer set and [installation procedure](INSTALLATION.md). This replaces the partition table and selects the loader to start. It is different from formatting the SD card or restoring all old settings.

### Advanced: restoring a full-flash backup

A full-flash backup is a copy of the board's internal storage. Restore only a known-good image for that exact board, in download mode, at offset `0x0`. This differs from writing the four installer files at their separate addresses.

It does **not** restore the SD card; matching SD files must be saved separately. Never publish a flash backup because it may contain passwords or private configuration.

## Asking for help

Include:

- Board and USB adapter model.
- AIEdge release/version and whether the problem is during USB installation, Wi-Fi setup or normal use.
- Exact error and last step that worked.
- Relevant tool output or device logs, with private details removed.

A **serial log** is text the board sends through its USB programmer. It helps when the website will not open. If you have never used one, say so in your report so the next steps can be tailored to your hardware.
