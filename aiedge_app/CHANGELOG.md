# Changes

## 0.2.0-dev10 (review candidate)

- Add a compact guided setup: Image, Alignment, Dials, Number format, Data and Finish. Next validates and applies the relevant step; finishing does not restart the camera or enable capture/MQTT.
- Separate the three alignment markers from dial editing. Keep all dials in one selector with X/Y controls, proportion locking, rim landmarks and a separate needle pivot.
- Keep the reference beside controls on desktop and visible while scrolling controls on mobile. Add grid, zoom and fit icons without altering image pixels.
- Reuse an unchanged reference and calibration. A different reference requires fresh geometry. Failed image loads retain the old reference.
- Add explicit, asynchronous camera checks and setup photos. Page navigation never probes or captures from the camera. Verified photos become reference candidates, not reading events or training labels.
- Add Settings for camera status, local HA storage and diagnostics. Lighting, exposure and camera-side orientation remain on the camera website because the capture API has no management endpoints.
- Fix stale navigation, legacy calibration bookmarks and selection resets. Use one specific setup error instead of duplicate notifications.
- Preserve trained models, native cores, physical calculation, saved reader assumptions and application options.


## 0.2.0-dev9 (review candidate)

- Remove position-error controls from Number format, including Advanced. Editing
  physical dial values preserves saved reader assumptions. New formats retain
  the provisional ±0.1 default until model/calibration error is validated; this
  is not a claim of measured model accuracy or a user-adjustable accuracy setting.
- Use full-resolution dial sampling in the server app. Sparse sampling remains
  available for diagnostics with a distinct pipeline identity. Four saved frames
  retained feasible ranges with full sampling; sparse sampling rejected one.
  This does not verify their reading accuracy. The trained models stay unchanged.
- Reject a reader result whose sampling/pipeline identity differs from the active
  reader instead of relabeling it as the current pipeline.
- Check passive camera readiness before each scheduled capture and distinguish
  missing hardware, unavailable settings, unsynchronized clocks and busy cameras.
- Show feasible total ranges and the register digits shared by every current
  range. Inconsistent estimates identify a conflicting dial group without
  guessing which individual dial is wrong or publishing a replacement total.
- Reconcile absolute offsets with existing cumulative-consumption bounds and
  replay the decisions after restart. Unbounded intervals retain possible whole
  turns. Changed interpretation starts a separate segment and retains old records.
- Current source and format identities gate status and optional MQTT output;
  pending or rejected captures cannot publish an earlier temporal estimate.
- Preserve reference, calibration, model and native-core contracts. This candidate
  does not flash the camera, change its settings or enable capture or MQTT.

## 0.2.0-dev8

- Handle stop requests during initialization and drain active requests and
  workers within a shared 35-second deadline. Supervisor stop grace is 45 seconds.
- Emit bounded readiness and shutdown events. A timed-out stop remains a failure.
- Recognition models, calibration, physical calculations and native cores remain
  unchanged. The approved three-image trial and two clean stops were verified.

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
