# Website authentication

Status: credential checking and persistent-storage foundation implemented and host-tested; required password setup is not yet implemented or deployed.

The selected product behavior is password protection for the entire device website: pages, images, readings, logs, settings and updates. This includes the application, Wi-Fi loader and storage-recovery website. Wi-Fi credentials are separate from the website password.

## Current evidence

The application routes use the shared Basic authentication filter. The filter now owns its active credential snapshot, checks header retrieval and the complete credential value, rejects partial/invalid credential configuration and encoder failure, and uses the AIEdge authentication realm. Initialization clears any previous active credential. No credential values are logged by this filter.

`tools/auth-tests/test_basic_auth.py` compiles the actual filter body with HTTP and base64 adapters. It checks correct credentials, every truncated prefix, every single-byte mutation and embedded NUL, oversized values, failed header reads, credential-source mutation, invalid configuration, encoding failure and reinitialization. Run with Python with the `ziglang` package installed. This is host coverage, not on-device authentication verification. The ESP32 managed target also compiled successfully on September 23, 2026; this candidate has not been flashed.

## Persistent credential store

`shared/WebsiteCredential.h` and `shared/WebsiteCredentialEsp.h` implement an SD-independent NVS credential record. The version-1 record has a random 16-byte salt, PBKDF2-HMAC-SHA256 verifier (20,000 iterations), and SHA-256 record checksum. No plaintext password is stored in this record. The checksum detects damaged records; it does not authenticate physical flash modifications. Work-factor latency and resistance to password guessing still need review on the board; this is not a final security qualification.

The store distinguishes uninitialized, first-time setup, ready and storage-error states. Missing records allow setup; corrupt records and inaccessible storage fail closed. A write is accepted only after commit and exact validated readback. Uncertain writes invalidate the active credential until a fresh load. There is no network reset operation. The eventual setup/change handlers must authorize calls to save; the storage class is not an authorization gate. The current legacy `wlan.ini` password path is unchanged and is not migrated by this module.

`tools/auth-tests/test_credential_store.py` exercises state transitions, every single-byte corruption of the record, truncation, failed reads/writes/commits, uncertain commits, readback mismatch, password change and reload. It also checks the actual ESP adapter with NVS and crypto-call substitutes. Those tests do not measure cryptographic implementation, physical power-loss behavior or flash retention. The SDK backend compiled in the managed ESP32 target on September 23, 2026. It is not connected to live HTTP access yet and has not been deployed.

## Remaining implementation and verification

- Require first-time password creation before exposing application data or controls. The current empty-configuration behavior still allows access; do not describe this build as password-required.
- Store the device credential independently of the SD card so removing/failing storage cannot remove protection. Avoid storing or returning plaintext passwords; initialize and persist credentials atomically and fail closed on corrupt or unavailable credential storage.
- Provide an explicit first-time setup authorization mechanism and physical recovery for a forgotten password. Recovery must not create an unauthenticated network reset endpoint. Preserve Wi-Fi and SD contents when resetting only the website password.
- Protect the loader and recovery routes as well as the existing application routes. Audit dynamically registered routes, static assets, errors, images, streams and diagnostics.
- Provide a beginner-friendly setup/change-password flow with show-password control, confirmation, clear saved/active state and no password in URLs, logs or exported diagnostic data.
- Verify browser behavior, fresh boots, lost SD, failed saves, invalid credentials, password changes, OTA transitions and recovery on the test board. Keep setup usable before enabling enforcement on that board.

Basic authentication on plain HTTP is not encrypted transport. A full-site password alone does not protect credentials from someone able to observe the network. Transport and credential storage must be addressed explicitly before presenting the complete implementation as secure.
