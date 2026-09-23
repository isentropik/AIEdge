# Image archive hardware trial — September 23, 2026

The first test-board capture did **not** reach the receiver. Archiving remains unverified on hardware and off by default.

The archive worker started, recovered an empty queue, and received one original camera image. SD admission rejected it before an upload: counters showed one handoff, one enqueue rejection, zero stored images and zero upload acknowledgments. The receiver received no capture record. A zero-byte `.settings.pending` file was preserved as failure evidence. Capture and rejected recognition finished without a crash; the web endpoints continued responding.

The trial's temporary archive files were removed, the original application configuration restored byte-for-byte, and the restored boot verified with archival disabled. The temporary HTTPS receiver and board-only firewall rule were stopped/removed. The production meter was not changed. No test image was added to training.

## File-writing correction

The archive writer used `open` followed by `fdopen`. Disassembly of the installed Xtensa newlib shows `_fdopen_r` calling `_fcntl_r` with `F_GETFL` and returning null on failure. The ESP-IDF FAT VFS registers file writing and synchronization but no `fcntl` handler; unsupported VFS calls return `ENOSYS`. This explains an exclusively created file being left empty before any write.

The correction uses direct descriptor writes, as the tested bundle installer does. It retains exclusive creation, bounded chunks, interrupted/partial-write handling, synchronization, close checks and hash-verified readback before publication. Existing partial files are not truncated or silently promoted.

Actual-source host tests pass publication/readback, partial and interrupted writes, zero/error writes, corruption detection, pending recovery and capacity checks. Worker/capture-binding regressions and all 28 transport cases pass. A corrected-device retest is still required; host success does not prove ESP32-to-receiver TLS or SD recovery.

Private evidence is under `needle-training/firmware-port-tests/archive-hardware-20260923` in the development workspace. It includes runtime snapshots, original configuration, empty pending-file evidence and library disassembly. Credentials and any future images are excluded from public artifacts.
