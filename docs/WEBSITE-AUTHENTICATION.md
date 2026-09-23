# Website authentication

Status: the password gate and first-time setup routes are integrated into local application, loader and recovery candidates. Host tests and both ESP32 builds pass. USB recovery is implemented in the candidate; this is not deployed or verified on hardware.

The selected behavior is password protection for the whole device website: pages, images, readings, logs, settings and updates. Wi-Fi credentials are separate. New credentials use username `admin`.

## Implemented

- The shared `WebsiteHttp` handler protects normal application routes, legacy AP setup routes, storage-recovery routes and loader routes. Missing configuration no longer means open access in these candidates.
- Before setup, only the home/setup screen is available; other data and control requests return Locked. Creating the password requires a random 32-byte setup code printed to local USB stdout after Wi-Fi initialization. It changes at restart and is not exposed through a website endpoint. Setup uses an exact custom header and POST body, never a URL parameter. A consumed token cannot replace an existing password.
- The embedded setup form includes password confirmation, an eye toggle, system/light/dark themes and a clear sign-in username. Passwords require 12–128 UTF-8 bytes and no control characters. A lost connection does not cause automatic resubmission of a potentially successful write.
- Settings now links to `/auth/password`. The authenticated password-change page requires the current password, confirms the replacement and sends an explicit custom change header. A successful verified save invalidates cached access; failures do not cause automatic retries. The endpoint is also registered in the loader and both recovery server paths.
- Configured devices challenge unauthenticated requests using HTTP Basic authentication. Invalid guesses are limited to one expensive verification per second. A verified in-memory fingerprint allows subsequent valid asset requests without repeated PBKDF2 work. Storage failures deny access.
- The shared NVS record is independent of SD storage. Version 1 stores a random 16-byte salt, PBKDF2-HMAC-SHA256 verifier (20,000 iterations) and SHA-256 checksum. No plaintext password is stored in this record. The checksum detects damaged records; it is not protection against physical flash modification.
- Writes require commit plus exact validated readback. Uncertain writes invalidate active access until a fresh load. No unauthenticated network reset operation exists.
- The loader preserves NVS on initialization failure, reports the problem over USB and stops startup. It no longer automatically erases Wi-Fi and website credentials.

The old `HTTP_USERNAME` / `HTTP_PASSWORD` fields in `wlan.ini` are not used by the new gate and are not automatically migrated or deleted. An upgrade without the new NVS record therefore requires first-time website setup. Do not deploy this change silently to an existing password-protected installation without handling that transition.

## Evidence and limits

- `tools/auth-tests/test_basic_auth.py` compiles the actual shared HTTP adapter with HTTP, base64, clock and storage substitutes. It checks setup, bad/missing/replayed codes, interrupted bodies, missing/wrong credentials, successful access across representative paths, oversized/malformed headers, header-read failures, throttling and failed storage/random generation.
- `tools/auth-tests/test_credential_store.py` covers credential/access states, every single-byte record corruption, truncation, reads/writes/commit faults, uncertain commits, readback mismatch, password changes, reload and cache invalidation. It checks the ESP adapter contracts with NVS/crypto substitutes and compiles the loader's actual NVS startup block to verify settings are preserved on errors.
- `tools/auth-tests/password_pages_test.cjs` executes the embedded page scripts with DOM/fetch substitutes. It checks confirmation and UTF-8 byte limits, eye toggles, UTF-8 Basic headers, success clearing, rejected responses and network failure handling. This is not a rendered browser test. HTTP adapter tests additionally cover successful password change, rejection without the action header, partial input, rejection of the old credential and failed-save lockout/reload.
- `tools/auth-tests/test_auth_routes.py` audits 78 handler assignments and checks setup registration in startup paths. This is a source audit, not runtime proof of every endpoint.
- Application and private loader candidates compiled successfully against the ESP32 SDK on September 23, 2026. A recorded test-board installation then verified USB setup-code delivery, loader authentication, rejection of setup-code replay, and password retention into the application. Representative unauthenticated application requests returned 401; the configuration was byte-identical after installation. This does not establish flash power-loss recovery, browser sign-in behavior or sustained performance.
- Visual preview was blocked by the browser's local-file policy. The setup page has not had rendered visual verification.

## USB-only password recovery

Connect the device to a computer and open a serial console at 115200 baud (8 data bits, no parity, 1 stop bit). Commands are case-sensitive; send a newline after each command. If the web installer's console cannot send text, use a serial terminal. These commands are not web endpoints.

1. To request a fresh first-time setup code, send `AIEdge AUTH SETUP`. This works only when the website password is not configured. It does not remove an existing password.
2. If the password is forgotten, send `AIEdge AUTH RESET`. Nothing is erased yet. The device prints a confirmation command with a random code.
3. Send that exact `AIEdge AUTH CONFIRM ...` command within 60 seconds. The code is single-use; an invalid or expired confirmation requires starting again.
4. A verified reset removes only `credential` in the `aiedge_auth` NVS namespace, invalidates cached access and prints a new setup code. Wi-Fi and SD files are preserved. If erase/commit/readback cannot be verified, access fails closed and the device does not report success.

The normal and SD-recovery application servers use a dedicated USB reader. The loader shares its existing Improv reader. Input is bounded, accepts only the explicit command prefix and rejects binary/oversized lines. The reader queues work onto the HTTP task instead of modifying credentials concurrently. UART initialization failure preserves settings and reports that recovery is unavailable; failed task allocation restores nonblocking console output before removing the driver. These readers assume their HTTP server remains alive until reboot; a future server teardown must stop the reader first.

Host tests cover parser fragmentation/noise/overflow, confirmation expiry/replay, failed or uncertain erases, exact NVS key/namespace contracts and actual queued callback execution. A physical read-only probe found that binary installer traffic could suppress the next console command until an extra newline. The correction clears rejected binary input after a 500 ms idle gap, preserving partially typed printable commands. Regression tests cover both cases. After an authenticated OTA installation using an uncompressed ZIP, the application passed the same physical binary-to-console probe without the extra newline; configuration bytes and password were preserved. The matching loader fix still needs this hardware check. A subsequent physical test verified password-only erasure, protected setup mode, password restoration and rejection of a consumed recovery challenge. The Wi-Fi connection stayed up and config.ini remained byte-identical. This used the extra-newline workaround on the installed build; power-loss recovery remains unverified.

## Remaining before deployment

- Verify the corrected loader binary-to-console boundary on hardware and coexistence with Improv Wi-Fi setup; the application boundary now passes. Confirm password-change browser behavior. USB setup and password-only recovery have passed the bounded test described above.
- Decide and test legacy credential migration and the installer-to-application transition. Check that no diagnostic mechanism republishes setup codes.
- Test real browser setup/sign-in, direct endpoint access, camera/SD failure, restarting, failed saves, OTA transitions and recovery on the test board. Measure password verification cost and UI/recognition contention.
- Serialize access if more than one server/task can call the shared state. Current ownership assumes startup followed by one active HTTP server task.
- Review transport protection. HTTP Basic authentication over plain HTTP is not encrypted. The password gate is not a claim of secure transport; use a trusted LAN during development. Work factor and security qualification remain pending.
