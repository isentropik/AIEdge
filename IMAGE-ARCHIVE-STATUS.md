# Image archive implementation status

Local development only. No live server or meter deployment.

## Startup configuration (September 22)

`ImageArchiveConfig.h` validates a bounded JSON configuration. Required explicit
`enabled` boolean; enabled configurations also require `host` (IPv4 or DNS name)
and `device_id`. Optional `port` defaults to 8766 and `timeout_ms` to 15000.
Unknown or duplicate fields, malformed/truncated JSON, invalid types, fractional
or out-of-range numeric settings, escaped/control-bearing identities and trailing
content are rejected. Failure resets the output to disabled. No credentials are
accepted through this parser. 128 actual C++ parser host cases pass via
`test_image_archive_config.py`, now included in the packaging test gate.

The server receiver selects its own local destination via `--folder`; requests
cannot choose arbitrary server paths. This is HTTPS receiver storage, not an
SMB/NFS client. Trust certificates and an authentication token remain necessary.

`CaptureArchiveBinding.h` joins the existing raw capture observer to the bounded
archive worker, preserving original bytes, a per-boot identity, monotonic capture
time, intended firmware/model/calibration identities and capture settings hash.
It rejects unexpected image geometry and supports disabling capture submission.
The profile describes intended inference, never verified successful recognition.
UTC remains unknown until capture-time clock mapping is implemented.

## Still incomplete

The opt-in configuration loader and binding are wired after flow/GPIO initialization.
No configuration file is installed and default behavior remains disabled. User-facing
settings/status, installation instructions and real TLS/server interoperability
validation remain. Device memory, capture timing, actual SD recovery and sustained
30-second operation also remain unverified. Host tests do not establish these.

## Bounded configuration file loading

`ImageArchiveConfigFile.h` reads `image-archive.json` (1024 bytes maximum),
`image-archive-ca.pem` (8192 bytes), and `image-archive-token.txt` (256 token
characters plus optional LF/CRLF) from a firmware-selected trusted directory.
Missing JSON or explicit disabled mode returns Disabled without requiring
credentials. Enabled mode requires all files. Invalid/failed loads clear output
configuration and credentials; the loader does not create files or log secrets.
Non-regular files and oversized inputs are rejected. TLS still performs actual
certificate parsing and peer verification before sending uploads: Ready means
configuration loaded, not connectivity or certificate verification proven.

Real-file loading tests and all 128 parser cases pass. The 28 settings/image
transport regression cases also pass after sharing destination validation.
The startup call site is now connected; user-facing status beyond startup logging remains incomplete.

## Opt-in startup binding

`ImageArchiveStartup.h` loads from `/sdcard/config` once per boot. It requires a
configured frozen PolarV1 geometry and no separate digital reader. The firmware
identity is the running application's IDF partition SHA-256 (not the entire
padded flash partition or the ZIP hash). The calibration identity is the generated
Polar geometry contract. Each boot receives a 128-bit random nonce; UTC remains
unknown. The spool directory is `/sdcard/image-archive`, created only after an
explicit enabled configuration passes validation. Worker startup is not a claim
that spool recovery or network connection succeeded.

`InitFlow` disables capture submission before configuration mutation. Archive
startup also disables submission before loading configuration. An unchanged
validated destination and frozen profile can resume the existing capture binding
without restarting or replacing its worker. Disabled, invalid or changed settings
leave new submissions off. Existing immutable queued records retain their original
destination. Changing destination, credentials or profile still requires a controlled
restart; no queue is silently redirected. Failures before worker creation can retry
at a later initialization boundary. Hardware reload behavior remains unverified.

Worker host regression now uses the actual destination validator rather than a
stub. Worker and capture-binding host tests passed after the startup changes.
Hardware startup/reload, SD fault behavior and resource headroom are unverified.

## Startup fault coverage and linked build

`test_image_archive_startup.py` compiles the actual startup function with simulated
platform boundaries. Thirteen isolated startup scenarios cover disabled/invalid
configuration, unsupported geometry, missing partition or hash failure, directory
creation/inspection errors, worker/binding failures and successful startup. Every
case checks repeated initialization cannot start a second worker or repeat setup.
The test is in the firmware packaging gate. This is not hardware startup proof.

The linked ESP32 build passed after integration: static RAM 53,880 / 327,680 bytes;
flash 1,611,656 / 1,945,600 bytes (82.8%). Dynamic PSRAM, TLS, task stacks and inference
allocations are not represented by that static RAM figure. Actual device memory
headroom and 30-second capture cadence remain required measurements.

## Read-only diagnostics

`GET /image_archive_status` uses the existing basic-auth filter and no-store
response header. It returns in-memory worker/capture/engine flags, handoff and
rejection counters, persisted/upload-acknowledged counters, pending/blocked/
acknowledged-awaiting-cleanup queue counts and the last filesystem inventory.
It does not return a server address, token, certificate, or remote folder, and
performs no SD scan or network call. These counters are runtime snapshots, not
a durable lifetime history. Handoff means queued RAM ownership, not SD durability;
upload acknowledgment means receipt validation, not training eligibility.

`test_image_archive_status.py` checks actual JSON serialization for disabled,
active, failure and capture-disabled/worker-active snapshots, counter values,
large integer text preservation, and the auth registration source. It is now a
packaging gate. Browser JSON numbers above 2^53 need care even though server text
preserves integer values. Runtime HTTP authentication remains a device check.

## Real loopback HTTPS receiver checks

`test_image_archive_tls.py` uses disposable certificates, loopback sockets and a
fresh temporary archive folder. It verifies settings-first image upload, exact
image readback, capture-record hash, immutable retry, rejection of untrusted
certificates/wrong hostnames/bad tokens, and an incomplete TLS handshake while
another client uploads. No external server or meter is contacted. The fixture
uses cryptography to generate a temporary key, never a production credential.

This complements the C++ transport's simulated ESP-IDF HTTP boundary tests; it
does not prove the installed ESP32 TLS stack interoperates with the user's server.
Actual trust provisioning, LAN behavior and server installation remain pending.

## Archive memory/network overlap

The worker now retains its admission reservation through upload after freeing the
just-spooled image. A capture arriving during network work is rejected before
allocating another PSRAM image. If a producer owns a pending job at a receive
boundary, the worker drains that job before beginning networking. Worker tests
assert allocations have been freed before upload and a new handoff during upload
does not allocate. This avoids retaining a queued large image behind slow HTTPS.

This is bounded best-effort archival, not a guarantee every capture is archived.
Slow storage/network work can cause counted handoff rejections. Capture/inference
is not blocked waiting for archival. TLS allocations can still overlap inference;
actual device memory high-water measurements remain necessary. Candidate f is
stale relative to this change; no device was updated.

## Resource measurement support

Worker-published snapshots now include monotonic sample time, internal/PSRAM free
bytes, largest free block, SDK minimum-free values and the worker stack low-water
value converted using sizeof(StackType_t). The installed Xtensa port uses an
8-bit StackType_t. Minimum-free heap values use the SDK's per-region accounting;
they are not an atomic measurement of one global worst instant. Current largest
block values are sampled outside heap operations and do not capture every short
allocation peak. Zero sample time means no worker sample, not zero usable memory.

Worker and JSON tests verify sample values and byte units with simulated platform
metrics. Real heap fragmentation, TLS/inference overlap and task stack headroom
still require the on-device trial. The HTTP handler only returns the saved sample;
it does not initiate a heap walk, SD scan or upload.


## Offline server/meter setup generator

needle_reader_v2/prepare_archive_setup.py now prepares a private local setup using
--host (IPv4/DNS), --folder (absolute server-local path), --ca-file (local trust
PEM), --certificate and --private-key (absolute paths on the server), plus a new
--output directory. Optional --device and --port select identity and listening
port. It validates inputs and parses the CA before output creation, creates a
random shared token, writes firmware-compatible meter configuration, and copies
the standard-library receiver/storage code and a shell-free launcher. It never
contacts a device/server or starts a listener. Existing outputs are refused.

Five unittest methods cover matching token/config, IPv4 and Windows paths,
eleven invalid-input cases with no output, invalid CA and literal shell-like
path characters. Test credentials live only in disposable temporary directories.
Windows ACL privacy must be established separately; chmod alone cannot promise
it. The CA parser does not verify the future server certificate's hostname or
chain. The target storage must support atomic hard links. The generator does not
install a service/firewall rule or authorize deployment. Actual server details,
certificate provisioning and approved meter configuration remain outstanding.


## Generated receiver integration validation

The setup generator now accepts an optional IPv4 --bind address (default remains
0.0.0.0); loopback testing uses 127.0.0.1. Its launcher executes the receiver in
the same process through runpy with an argument list, without a shell or child
server process. The exact generated receiver, generated token and CA/config were
used in a real local TLS process test. Wrong credentials and untrusted TLS were
rejected before archive creation; settings and image uploads succeeded, saved
bytes and receipt hashes matched, and duplicate submission returned 200 with one
capture record. Review status stayed unreviewed/training_eligible=false.

The initial test attempts passed upload assertions but failed Windows temporary
cleanup: the venv launcher did not provide a wait handle for the actual receiver.
The harness now launches base Python directly and waits for the actual process;
the end-to-end test passed including cleanup. Disposable keys and token files
were removed. This proves local generated-setup interoperability only, not ESP32
TLS interoperability or the user's storage server filesystem/network. No live
meter or storage server was contacted; no model was trained/deployed.
