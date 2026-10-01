# Changes

## 0.2.0-dev8

- Stop requests are handled during initialization, before capture workers start.
- An app stop gives in-flight requests and workers a shared 35-second drain
  deadline; Supervisor allows 45 seconds before a forced stop.
- Startup, clean stops and drain timeouts produce structured app log events.
- Coverage checks verify that imported runtime modules are packaged and require
  startup/shutdown regressions. The Linux packaged-runtime test now checks a
  successful SIGTERM exit as well as persistent storage.
- Recognition, physical calculations, dependencies, calibration, saved images
  and capture/MQTT options retain their dev7 behavior. No camera firmware change.

## 0.2.0-dev7

- Linux camera connections request smaller TCP segments before connecting,
  reducing the impact of large-packet loss without changing the camera or LAN.
- Connection attempts share the remaining capture deadline. IPv4, IPv6, TLS
  verification and platforms without this socket option retain their behavior.
- Image hashes, capture identity checks and the total capture deadline stay
  enforced. Failed or partial transfers remain rejected, with no capture retry.
- Models, reference images, calibration, number format and capture/MQTT settings
  are unchanged. This update does not flash or restart the camera.

## 0.2.0-dev6

- Camera transfers use the complete 20-second capture deadline. A separate
  five-second idle timeout no longer cuts off an otherwise valid response.
- Connection setup stays bounded to five seconds; redirects, malformed images
  and capture metadata checks retain their existing behavior.
- Capture, MQTT, calibration, number formatting and saved images are preserved.
  This update does not change camera firmware or start automatic capture.

## 0.2.0-dev5

- Unchanged dial regions can reuse preprocessing and model output after alignment.
  Changed pixels or alignment use the full processing path.
- Rejected frames and model failures clear the affected reusable results.
- This changes the recognition pipeline identity. Review and save Number format
  for the new pipeline before enabling capture or MQTT.
- Archived-image parity tests pass. The nine different test photographs needed
  full processing, so no live-camera speedup is established.

## 0.2.0-dev4

- Larger phone and tablet touch targets, input text and crop handles.
- Clearer Home Assistant installation and test status.

## 0.2.0-dev3

- Home Assistant app repository metadata and branch-specific installation guide.
