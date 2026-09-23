# AIEdge installer build

The website bundles ESP Web Tools 10.4.0 locally. Upstream is credited in the website, CREDITS.md and vendor/NOTICES.txt. No firmware binaries are changed by this build.

Run `npm ci --ignore-scripts`, `node discovery.test.mjs`, then `node build.mjs` from this directory. package-lock.json pins all dependency versions. The build fails if an upstream patch anchor changes.

## USB setup fix 1

The unmodified flow resets before closing and reopening USB. The user reported discovery working only after Logs & Console > Reset device > Back. Our patch performs one reset on the already-open port if normal discovery fails, waits 2.5 seconds for startup, then allows 30 seconds for discovery. It uses the same esptool-js HardReset procedure as the console, explicitly releasing DTR first. It does not erase, reflash or send credentials. Busy ports are not reset. Persistent failures leave the manual log/installation options available and are distinguished from successful provisioning. A connection attempt may restart a board whose firmware does not respond to Improv.

Post-flash Next opens Wi-Fi setup whenever discovery succeeds, including installations without erase. The normal firmware flash and binary verification are unchanged.

Automated recovery and integrity checks pass. The user is testing the physical reset/discovery behavior; do not claim that hardware validation is complete until the result is recorded.

## Wi-Fi password visibility

The USB Wi-Fi dialog includes an Show password eye button inside the password field. Toggling it only changes the password field type, preserving the entered value. It does not submit credentials. The setup hotspot page uses the same eye button. `password-fixture.html` exercises the actual bundle against a simulated serial device, without connecting to hardware.

## Faster USB installation

`flash-speed.mjs` wraps the pinned upstream flash operation: attempt 460,800 baud, then at most one 115,200-baud retry for initialization or write errors after transport cleanup succeeds. Each attempt uses the same verified image and restarts the full write. A completed full erase is not repeated. Unsupported boards, firmware download failures, unavailable ports, permission errors and failed cleanup do not trigger this retry. Logs and Improv Wi-Fi setup remain at 115,200 baud.

Run `node flash-speed.test.mjs` and `node discovery.test.mjs` before `node build.mjs`. The tests cover both speeds, bounded failure, erase preservation and failures that must not retry. Physical speed, adapter compatibility and elapsed installation time still require hardware testing.
