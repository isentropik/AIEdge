# Archive file-write regression tests

These tests use temporary folders on your computer. They do not contact a meter,
upload an image, or change device settings.

Requirements: Python 3, a C/C++ compiler, and the mbedTLS source tree from the
ESP-IDF version used to build AIEdge. Run:

```sh
python run_spool_failures.py --mbedtls /path/to/esp-idf/components/mbedtls/mbedtls
```

Use `--cc` and `--cxx` to select compiler executables. Alternatively,
`--zig-python /path/to/python` uses that Python installation's `ziglang` module.
Nothing is downloaded automatically.

The test compiles the production archive headers and SHA implementation. It
injects short writes followed by an out-of-space error, synchronization failure,
and close failure into both settings and image files. It checks that descriptors
are closed, incomplete files remain untouched, no final file appears on failure,
and the archive engine does not report an image as stored. Fully written pending
files can recover only after their normal hash/readback checks pass. A compile
guard rejects reintroducing `fdopen`, whose `fcntl` dependency is unsupported by
the ESP32 FAT driver.

This is host fault injection. It does not prove physical SD power-loss recovery,
ESP32-to-server TLS interoperability, or capture timing on hardware.


## Destination changes and restart recovery

Run `run_destination_queue.py` with the same `--mbedtls` and optional
`--zig-python` arguments. It uses the real queue engine, SD-file formats and SHA
implementation on a temporary filesystem. It checks that changing the server,
port, token, CA certificate or device identity selects a separate queue, while
changing only a timeout preserves it. A fresh engine recovers the original queue
when its original configuration is restored. Legacy unbound files are preserved
and never adopted by the new destination. No network or camera is used.


Archive settings and recovery tests (requires source trees for mbedTLS and cJSON):

```sh
python run_settings.py --mbedtls /path/to/mbedtls --cjson /path/to/cJSON
```

Use `--zig-python /path/to/python` if that interpreter provides `ziglang`, or select `--cc` and `--cxx`. The tests compile production settings, HTTP, hashing and file code. SDK HTTP calls are simulated, so these tests do not prove basic-auth registration or physical power-loss safety. They cover bounded/partial requests, guard contention, token retention/redaction, stale revisions, legacy migration, journal refusal and 249 crash/torn-write/recovery cases.

Run the browser-state unit tests with `node settings_form.cjs` and `node status_ui.cjs`. Visual checks still require a browser.

## Upload timeouts and retry

```sh
python run_transport.py --mbedtls /path/to/mbedtls --cjson /path/to/cJSON
```

The same compiler options apply. This compiles the actual uploader with real
spool files, hashing and JSON parsing. HTTP and the monotonic clock are simulated.
It tests partial writes, bad receipts, HTTP errors, timeouts, invalid destinations,
cleanup, and a single shared network budget across settings and image requests.
The slow-request case must retain the image and allow a subsequent valid retry.
