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
