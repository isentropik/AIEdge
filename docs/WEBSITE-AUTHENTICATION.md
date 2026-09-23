# Website authentication

Status: the password gate and first-time setup routes are integrated into local application, loader and recovery candidates. Host tests and both ESP32 builds pass. This is not deployed; recovery UX and on-device verification remain incomplete.

The selected behavior is password protection for the whole device website: pages, images, readings, logs, settings and updates. Wi-Fi credentials are separate. New credentials use username `admin`.

## Implemented

- The shared `WebsiteHttp` handler protects normal application routes, legacy AP setup routes, storage-recovery routes and loader routes. Missing configuration no longer means open access in these candidates.
- Before setup, only the home/setup screen is available; other data and control requests return Locked. Creating the password requires a random 32-byte setup code printed to local USB stdout after Wi-Fi initialization. It changes at restart and is not exposed through a website endpoint. Setup uses an exact custom header and POST body, never a URL parameter. A consumed token cannot replace an existing password.
- The embedded setup form includes password confirmation, an eye toggle, system/light/dark themes and a clear sign-in username. Passwords require 12–128 UTF-8 bytes and no control characters. A lost connection does not cause automatic resubmission of a potentially successful write.
- Configured devices challenge unauthenticated requests using HTTP Basic authentication. Invalid guesses are limited to one expensive verification per second. A verified in-memory fingerprint allows subsequent valid asset requests without repeated PBKDF2 work. Storage failures deny access.
- The shared NVS record is independent of SD storage. Version 1 stores a random 16-byte salt, PBKDF2-HMAC-SHA256 verifier (20,000 iterations) and SHA-256 checksum. No plaintext password is stored in this record. The checksum detects damaged records; it is not protection against physical flash modification.
- Writes require commit plus exact validated readback. Uncertain writes invalidate active access until a fresh load. No unauthenticated network reset operation exists.
- The loader preserves NVS on initialization failure, reports the problem over USB and stops startup. It no longer automatically erases Wi-Fi and website credentials.

The old `HTTP_USERNAME` / `HTTP_PASSWORD` fields in `wlan.ini` are not used by the new gate and are not automatically migrated or deleted. An upgrade without the new NVS record therefore requires first-time website setup. Do not deploy this change silently to an existing password-protected installation without handling that transition.

## Evidence and limits

- `tools/auth-tests/test_basic_auth.py` compiles the actual shared HTTP adapter with HTTP, base64, clock and storage substitutes. It checks setup, bad/missing/replayed codes, interrupted bodies, missing/wrong credentials, successful access across representative paths, oversized/malformed headers, header-read failures, throttling and failed storage/random generation.
- `tools/auth-tests/test_credential_store.py` covers credential/access states, every single-byte record corruption, truncation, reads/writes/commit faults, uncertain commits, readback mismatch, password changes, reload and cache invalidation. It checks the ESP adapter contracts with NVS/crypto substitutes and compiles the loader's actual NVS startup block to verify settings are preserved on errors.
- `tools/auth-tests/test_auth_routes.py` audits 78 handler assignments and checks setup registration in startup paths. This is a source audit, not runtime proof of every endpoint.
- Application and private loader candidates compiled successfully against the ESP32 SDK on September 23, 2026. No candidate from this authentication work has been flashed. No cryptographic implementation, hardware timing, flash power-loss, browser sign-in or retention claim follows from the host tests.
- Visual preview was blocked by the browser's local-file policy. The setup page has not had rendered visual verification.

## Remaining before deployment

- Finish local USB delivery and password-only recovery so users cannot be stranded, preserving Wi-Fi and SD contents. Add a usable authenticated change-password screen/route; the core operation currently has only host coverage.
- Decide and test legacy credential migration and the installer-to-application transition. Check that no diagnostic mechanism republishes setup codes.
- Test real browser setup/sign-in, direct endpoint access, camera/SD failure, restarting, failed saves, OTA transitions and recovery on the test board. Measure password verification cost and UI/recognition contention.
- Serialize access if more than one server/task can call the shared state. Current ownership assumes startup followed by one active HTTP server task.
- Review transport protection. HTTP Basic authentication over plain HTTP is not encrypted. The password gate is not a claim of secure transport; use a trusted LAN during development. Work factor and security qualification remain pending.
