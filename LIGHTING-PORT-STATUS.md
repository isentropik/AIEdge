# Lighting changes: local, not deployed

## Implemented

- Explicit `LEDType = SK6812_RGBW` sends GRBW, four bytes per pixel. Existing
  WS2812/WS2812B/SK6812/WS2813 selections retain three-byte GRB behavior.
- `LEDColor = R G B [W]` accepts an independent 0–255 W value. Omitted W is zero;
  nonzero W on an RGB format is rejected. White-only is `0 0 0 255`.
- Both legacy and IDF5 RMT encoders transmit the fourth component in RGBW mode.
  Internal four-byte Rgb storage is retained for compatibility: the fourth byte
  represents dedicated W only in this explicit mode, not alpha blending. GPIO
  flash writes every channel explicitly; RGBW buffers initialize with W=0.
- The camera passes its existing 0–8191 PWM intensity to the GPIO flash handler.
  External R/G/B/W are scaled together, without modifying configured channels.
  Zero intensity and off commands transmit zero on every channel. Built-in flash
  selected through GPIO now uses the existing PWM channel rather than binary
  gpio_set_level; non-PWM builds can only switch that built-in output on/off.
- The configuration template exposes RGBW selection and a W input. The actual JS
  parser/writer preserves four values and converts legacy missing W to zero.

## Verification

ESP32 build succeeded (27.24 seconds build time, not device runtime).
`needle_reader_v2/test_firmware_leds.py` in the parent workspace tests the actual
encoder function bodies with peripheral stubs. 144 combinations cover RGB/RGBW,
brightness/off, 19 pixels, and several fragmented buffer capacities. All 19 RGBW
pixels produce 76 bytes; RGB produces 57. White-only output and reset signaling
are covered. Brightness rounding is checked for all 2,097,152 combinations of
8-bit channel value and 13-bit duty. These are not hardware/timing measurements.

`test_led_config_ui.cjs` checks four real parser/writer round trips, including old
three-value configurations. Browser rendering and packaged generated HTML remain
to verify. It uses a normal trailing System section; the upstream parser's
end-of-file handling of an isolated GPIO-only document still needs a separate fix.

## Remaining before deployment

- Verify the installed 19-pixel strip is GRBW, and test physical off, intensity
  0/1/intermediate/full, white-only output, pixel count and color order.
- Verify built-in PWM routing and capture/reference/stream exposures on hardware.
- Verify the new live preview intensity controls in a browser and on hardware;
  the explicit Save button now persists through a recovery journal and activates
  at a camera boundary. Physical save/recovery and browser behavior remain to test.
- Make GPIO reconfiguration safe at a controlled boundary. Current global LED
  driver lifetime/configuration cannot yet be changed arbitrarily in place.
- Handle RMT failures and waits explicitly instead of assuming output succeeded;
  existing waits/concurrent access still require the responsiveness work.
- Finish web asset generation/rendering, explicit invalid-setting feedback and
  exact deployment/recovery proposal. No physical LEDs were activated by this work.
## Camera ownership and asynchronous streaming

Capture transactions share a recursive FreeRTOS mutex. Manual camera/light and
preview-edit handlers return 503 with Retry-After when busy. Recognition waits
at most one second before failing a contended capture stage.

Streaming now uses a single admitted asynchronous HTTP worker. It owns the camera
only while applying settings, acquiring and copying one JPEG, and cleaning up
illumination. It returns the camera framebuffer and releases ownership before
network sends or pacing delays. Temporary JPEG storage is bounded to 1 MiB in
PSRAM and freed on send failure. Invalid frames and allocation failures stop the
stream. Contention exceeding one second currently ends the stream; resumable
pause/status behavior remains to implement. Camera/LED settle time and fairness
still need hardware verification. There is no queued-frame backlog.

The async request is completed on worker exit and task-creation failure. Only one
stream is admitted; false/0 no longer enables the flashlight. The host lifecycle
test covers query errors, duplicate admission, async/task creation failure and
worker cleanup. The stream body has 14 failure fixtures that assert camera
ownership is released before sends/delays, no null framebuffer is returned and
allocated JPEGs are freed. The guard test covers 16 concurrent initializers,
recursive ownership, contention/release, allocation and HTTP response failures.

Important test correction: Zig's -O2 defines NDEBUG by default. Earlier C++
assertion-based reports were insufficient evidence. All 17 host scripts were
rerun successfully with explicit -UNDEBUG on September 22; see
`needle-training/firmware-port-tests/assertions-enabled-suite.json` in the parent
workspace and per-test logs. Windows crash dialogs are disabled only for the
Python test processes and their children. Numerical Python comparison checks
remain separate evidence. This does not verify ESP32 scheduling or LED hardware.

The new stream.html page provides a 0–100 slider using authenticated
/stream_intensity POST requests. The server queues an atomic preview-only value;
frames apply it under camera ownership and restore the configured intensity before
release. New streams reset the temporary override. The UI coalesces rapid changes,
allows one request in flight and aborts requests after three seconds. The response
says pending preview frame, not physically applied. Zero uses the existing off
scaling. Main navigation no longer closes the stream popup automatically.

Endpoint tests verify bounds, invalid inputs, queueing while the camera is busy
and unchanged configured intensity. Stream tests now include 0/1/100 overrides and
restoration (17 fixtures). Node tests cover coalescing, one in-flight request,
errors, bounds and zero. ESP32 compilation succeeds. Browser rendering, live
application acknowledgement, reconnect races, save/recovery on hardware, exposure
settling, fairness and physical responsiveness remain to verify or implement.
Direct emergency shutdown lighting is outside normal transaction ownership;
boot initialization precedes normal users. No firmware has been deployed.


## Transmission failure handling (September 22)

SmartLed returns an error instead of aborting when busy. Rejected submissions
return the completion token, and buffers swap only after successful submission.
The global external-light path waits at most 100 ms plus one RTOS tick at each
of its prior-transmission and new-completion checks. Timeouts preserve buffer
ownership; a missing interrupt is never treated as successful completion. Errors
are logged and returned to the camera. Built-in PWM errors also return failure.
Recognition rejects failed illumination before requesting a frame and attempts
light-off cleanup.

Actual-method tests cover 100 rejected submissions, busy responses, bounded
waits, unchanged buffers on failure and late completion. Capture tests include
illumination rejection; stream, manual-capture and RGB/RGBW regressions pass
with platform stubs. Physical hardware remains unverified. Off is not guaranteed
after a driver fault. Initialization failures, non-global driver lifetime and
remaining call-site propagation remain follow-up work.

The preview stream now rejects failed light activation before capture and ends
on a failed light-off, restoring saved intensity and releasing camera ownership
and copied frame memory. It sends no image payload after either failure. The
recognition capture also rejects failed light-off and frees its decoded image
without marking the capture timestamp valid. Actual-body host tests pass 19
stream fixtures and 14 recognition capture fixtures, including both failures.
These tests check cleanup and reporting, not physical extinguishing of LEDs.

File and legacy HTTP snapshots now reject failed light activation/off before
writing or sending image bytes, and tolerate a missing discarded framebuffer.
File snapshots additionally reject unsupported extensions, empty/invalid data,
codec failures, open errors, short writes and close errors instead of returning
success. Buffers/framebuffers are released on each path. The file-body fault
tests pass. The dedicated HTTP snapshot/callback harness now also passes,
including lighting, empty camera/demo buffers, headers, codec, data-chunk and
terminal-chunk failures. Empty payloads are rejected, failed encoding no longer
sends a success terminator, and terminal transport errors propagate to callers.
The save-to-file endpoint returns HTTP 500 rather than a filename on capture
failure; the legacy flow wrapper clears its timestamp and propagates failure.
These are platform-stub tests, not a physical network/camera validation.
File writes are not atomic replacements: failure may leave a partial
destination, so this is not a claim of file rollback or power-loss recovery.
