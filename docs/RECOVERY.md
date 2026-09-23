# Recovery and troubleshooting

| Symptom | Check |
| --- | --- |
| Setup network missing | Power, board type, flash verification, boot-mode jumper and serial log. |
| `.local` fails | Use `192.168.4.1` on the setup AP, or the DHCP address on home Wi-Fi. Some clients/VLANs block multicast discovery. |
| No networks | Use 2.4 GHz Wi-Fi, move closer, rescan, or enter a supported hidden network manually. |
| Connection failed | SSID, password, signal, authentication type and DHCP. |
| Clock sync failed | Check DNS/Internet/NTP access; TLS certificate checks require a valid clock. |
| Download failed | Check GitHub/release-asset access, asset availability and serial errors. The older local-server loader instead needs its PC server; reflash to change that behavior. |
| Verification failed | Do not bypass hashes. Check SD health and installer/package matching. |
| SD mount failed | Check FAT32, insertion and card health. The loader does not auto-format. |
| Staging conflict | Preserve logs and partial files. Interrupted/conflicting directories are deliberately retained for diagnosis. |

## Serial recovery

Keep exact known-good flash files and matching SD configuration. An original full-flash backup can be restored at offset `0x0` in download mode, using the image for that board. This restores flash only, not SD changes. Never publish the backup; it may contain credentials.

The loader remains in the other OTA slot, but this is **not automatic rollback**. SDK rollback is disabled in the initial setup; a failed main boot can require serial recovery. Do not repeatedly reflash or clear staging files before diagnosing the problem.

Reflashing the complete installer set resets OTA selection and replaces its partition table. Use the intended development device and recovery copies. Firmware rollback, factory reset and SD formatting are different operations.
