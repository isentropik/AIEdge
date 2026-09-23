# Image archive hardware trial — September 23, 2026

**Final result:** one original queued camera image was delivered over verified HTTPS, its stored bytes and metadata matched, and the board acknowledged delivery and cleared the queue. Original settings were restored and archiving remains off by default. Earlier failed attempts and their fixes are documented below. This verifies one delivery and restart recovery, not sustained operation or reading accuracy.

The archive worker started, recovered an empty queue, and received one original camera image. SD admission rejected it before an upload: counters showed one handoff, one enqueue rejection, zero stored images and zero upload acknowledgments. The receiver received no capture record. A zero-byte `.settings.pending` file was preserved as failure evidence. Capture and rejected recognition finished without a crash; the web endpoints continued responding.

The trial's temporary archive files were removed, the original application configuration restored byte-for-byte, and the restored boot verified with archival disabled. The temporary HTTPS receiver and board-only firewall rule were stopped/removed. The production meter was not changed. No test image was added to training.

## File-writing correction

The archive writer used `open` followed by `fdopen`. Disassembly of the installed Xtensa newlib shows `_fdopen_r` calling `_fcntl_r` with `F_GETFL` and returning null on failure. The ESP-IDF FAT VFS registers file writing and synchronization but no `fcntl` handler; unsupported VFS calls return `ENOSYS`. This explains an exclusively created file being left empty before any write.

The correction uses direct descriptor writes, as the tested bundle installer does. It retains exclusive creation, bounded chunks, interrupted/partial-write handling, synchronization, close checks and hash-verified readback before publication. Existing partial files are not truncated or silently promoted.

Actual-source host tests pass publication/readback, partial and interrupted writes, zero/error writes, corruption detection, pending recovery and capacity checks. Worker/capture-binding regressions and all 28 transport cases pass. A corrected-device retest is still required; host success does not prove ESP32-to-receiver TLS or SD recovery.

Private evidence is under `needle-training/firmware-port-tests/archive-hardware-20260923` in the development workspace. It includes runtime snapshots, original configuration, empty pending-file evidence and library disassembly. Credentials and any future images are excluded from public artifacts.

The reproducible [file-failure regression](../tools/image-archive/tests/README.md) now injects write, sync and close failures into both file types and checks engine accounting. It is included in the local firmware packaging gate. This remains host evidence, not the pending corrected-device retest.

## Corrected SD writer: hardware result

Loader 0.1.11-test8 installed the candidate with application SHA-256 `7fd72c3474aaddf0b1b974dacb74f8dbc9daefa9be6308fd8b444ee0e5fa8420`. One approved camera capture was handed off and saved to SD: stored=1, enqueue_rejected=0. Original settings were restored after the bounded trial. The failed empty settings file from the first trial was copied as evidence and only that verified empty artifact was removed before retrying.

Upload still failed. USB logs state `HTTP_CLIENT: No transport found` and request enabling HTTPS. The application SDK configuration had `CONFIG_ESP_HTTP_CLIENT_ENABLE_HTTPS` disabled. The queued image remains preserved; it was not falsely acknowledged or deleted. This is a second, separate build-configuration defect, not proof of receiver/TLS interoperability. A follow-up must retry that same image without taking another capture.

Evidence: `archive-hardware-retest-20260923`, installation `recorded-20260923T174730Z`, USB `passive-20260923T175351Z.bin`. The temporary receiver and firewall rule were removed. The production meter remains untouched.

## HTTPS build and installer memory pressure

HTTPS is now enabled in the application SDK defaults, with a compile-time guard preventing an archive build without it. The first installation attempt stopped safely before application activation: SD verification failed at offset 49152 in `html/flow_overview.jpg`. USB reported an SD DMA allocation failure with about 4 KB internal heap free and a largest block of 1856 bytes. The old application and queued image were retained.

The verifier now releases manifest text and buffers before asset reads. Staging releases redundant parsed-manifest and inventory copies, then closes the ZIP and frees its indexes before final verification. File verification uses a 1 KB buffer. Length, hash, CRC, sync, readback and activation checks remain intact. All 76 verifier, boot-selection, index, transaction and miniz staging host cases pass; diagnostics tests also pass. A fresh immutable private package preserves the failed staging tree for diagnosis. Hardware results follow separately.


The memory correction passed on the test board: loader 0.1.11-test10 completed staging, firmware verification and application startup. Diagnostic samples during asset verification showed tens of kilobytes of free internal memory instead of the earlier 4 KB failure. This is one successful installation, not sustained or power-loss coverage.

The subsequent queued-image retry performed zero captures and delivered the settings descriptor over verified HTTPS. The image request failed because its base64 metadata header exceeded ESP-IDF's default transmit buffer. The queue was preserved and original settings restored byte-for-byte. The uploader now sizes its transmit buffer from the bounded metadata length plus 1024 bytes of header space (at most 5120 bytes). The actual-source transport test checks a real metadata header larger than 512 bytes fits, with all 28 transport outcomes still passing. Final image delivery requires another same-image retry.

## Verified queued-image delivery

Loader 0.1.11-test11 installed application SHA-256 `67d7fd877bed293cbe0ff792c81d9c36f4e3f0850028f797080fa20a82296166`. Installation and application startup were recorded in `recorded-20260923T182559Z`.

The original queued JPEG survived application updates and restarts. With capture disabled, the corrected application delivered that image to the same temporary LAN HTTPS receiver. Independent file checks verified:

- One 21,723-byte JPEG, 640 × 480, SHA-256 `a85b14af7ff978ec3282eda684df5ace8562735078bf589badc38252e0c2ee14`.
- Matching settings and metadata hashes, original capture monotonic timestamp and original capture firmware/model/calibration identities. The uploading firmware did not replace capture provenance. UTC remained unknown.
- Zero new capture attempts; one upload acknowledgment; zero upload failures, cleanup failures, pending records or blocked records in the final trial.
- Original configuration restored byte-for-byte; temporary credentials removed; archive worker stopped after the restored boot. Temporary receiver and board-only firewall rule removed.

The image remains unreviewed and excluded from training. This test does not verify meter-reading accuracy, concurrent recognition performance, arbitrary server compatibility or physical SD/power-loss recovery. Private evidence is in `archive-https-header-retry-20260923/verification.json`; no private image, certificate or token is published. The public web-installer binary is unchanged.
