# Configuration saving: local implementation in progress

The IDF FAT VFS delegates rename to FatFs f_rename, which does not provide a
replace-existing atomic rename. Do not implement saving by removing config.ini
and hoping the next rename succeeds.

`ConfigJournal.h` is a portable transaction core. `FileConfigStorage.h` now
implements bounded binary reads, full writes, fflush/fsync/close checks and
readback through the core. InitFlow invokes recovery before parsing configuration.
The authenticated Save endpoint is connected to this path. It records complete old/new config bytes with version, bounded
lengths and CRC32, writes/syncs and verifies the journal before touching config,
then writes/syncs and verifies config before removing the journal. It preserves
a valid journal when restoration cannot be verified. CRC32 detects incidental
corruption here; it is not an authentication or security mechanism.

Recovery accepts an exact old/new config. Missing or partial config is restored
from the verified journal's old copy. An invalid journal fails closed and retains
evidence. External edits must not run concurrently or bypass recovery while a
journal exists. The storage adapter must distinguish missing from unreadable,
bound reads, check full writes, fflush/fsync/close and verify readback. A cleanup
failure after verified persistence is explicitly CleanupPending, not an assertion
that the old value remains saved. Commit must not continue when recovery cannot
clean up a prior journal.

`CameraConfigEdit.h` edits only one LEDIntensity numeric token in one active
TakeImage section, preserving comments, whitespace, line endings and all other
configuration. Missing/duplicate/invalid settings and disabled-section ambiguity
are rejected, not silently repaired.

Host tests inject power loss at storage operation boundaries, partial journal and
config writes, missing config, corrupt journal bytes, baseline conflicts and
cleanup failure. They verify the CRC known vector and byte-preserving edits.
They pass with assertions enabled. This is not physical SD-card power-loss proof.

Remaining integration:

- Integrate all other config upload/delete/write entry points with recovery.
  Main initialization now recovers first, rejects missing/empty/oversized input,
  and marks storage unsafe on recovery failure. Normal recognition, single-step
  processing and take-image-only flow reject unsafe storage. This flag indicates
  storage/recovery readiness; it is not a full semantic config validator.
  Existing hot-reload concurrency still needs a complete audit.
- Browser-rendered Save/status verification and on-device persistence/recovery
  checks. The implemented endpoint holds camera ownership, validates and persists
  the scalar change, verifies readback, then updates CCstatus, CFstatus and camera
  duty. It reports saved/active/cleanup-pending separately. Uncertain failed
  restoration marks storage unsafe and blocks recognition.
- The Save button drains pending preview requests before saving and disables
  controls until the request finishes. An uncertain HTTP outcome is not silently
  retried or described as unchanged. No reboot is requested for intensity saving.
- File-manager uploads/deletes now refuse mutations while a config journal exists
  or cannot be checked. Downloads remain available. Other write paths still need
  audit; this does not claim every upstream config update uses the journal.

No live file, device setting or firmware was changed by this work.

Actual InitFlow and adapter tests use real temporary Windows files to verify
interrupted/completed transactions, missing/empty configs, corrupt journals,
camera contention, bounded reads and subsequent recovery. The controller fixture
also verifies no stage executes when storage is unsafe. These tests do not
establish ESP32 SD power-loss behavior or semantic validation of every setting.

The actual Save endpoint passes fault-injected storage tests for activation,
busy/invalid/unsafe requests, restored failures, uncertain state and pending
cleanup. A prior transaction's cleanup error cannot count as success for a new
value. File-manager mutation checks and UI request-draining tests pass. Physical
SD durability, browser rendering and live uptime/persistence remain unverified.

Desktop browser verification now covers the actual HTML/JS against a loopback-only
mock: initial value, slider request, successful Save, cleanup-pending Save, HTTP
500, disabled controls during Save and a three-second timeout. The timeout text
was clarified and the popup made resizable/scrollable with more height. Local
mock and tab were closed afterward. See preview-browser-results.json for asset
hashes and limitations. This does not verify real MJPEG, mobile layout or ESP32
response time, and the changed popup launch dimensions still need exercising.
