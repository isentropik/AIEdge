# Development status

| Check | Evidence / limitation |
| --- | --- |
| Main package | Clean ESP32 build and 73 completed local test scripts. These are not 73 hardware tests. |
| Package integrity | Production host stager verified 78 runtime files; full ZIP hash recorded. |
| Initial loader | Four flash regions hash-verified; board boot confirmed setup AP and mounted SD. |
| Initial transfer | Failed before receiving package bytes from the PC. Windows inbound blocking was suspected; no firewall change succeeded. |
| GitHub loader, mDNS, network picker | Compiled successfully for ESP32. Setup JavaScript syntax and package integrity checks pass. These changes are not yet flashed or verified end to end on hardware. |
| Accuracy | Limited human-labelled tests on one meter. Not coverage of every position, lighting or meter. Unlabelled predictions are not accuracy evidence. |
| Timing | Sustained valid-reading cadence and end-to-end duration on the target remain to be measured. |
| Recovery | Original board flash preserved; automatic bad-app/power-loss rollback unproven. |
| UI | Initial branding/style implemented; full mobile/device rendering verification incomplete. |

See the implementation notes for detailed limitations. Do not replace invalid or unknown readings with plausible-looking values.
