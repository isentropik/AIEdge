# Changes

## 0.2.0-dev21 (draft; not deployed)

- Add a short capture trial to Captures, with progress, unique/repeated image counts and Stop. It makes at most three acquisition attempts without enabling automatic capture or changing options.
- Keep the request ID across page reloads. Resolve lost replies through status checks; an explicit retry reuses the same ID rather than starting another trial.
- Preserve verified images when cancelling or rejecting capture timing. Interrupted trials stay stopped after an app restart.
- Reject damaged trial records without replacing them, and keep the rest of the website available. Models, calibration and number format are unchanged from dev20.
- Check the active reader before the first image; pending recognition no longer falsely changes trial identity.
- Document trial limits and correct stale Linux packaging notes.

## 0.2.0-dev20 (draft; not deployed)

- Use the existing floating-point main-dial model to avoid large jumps seen in saved-image tone tests. The secondary model is unchanged.
- Validate the separate model input/output contracts while preserving native alignment, needle pivots and rejection checks.
- Keep old model results and reviews in history. A model change requires saving the number format against the new reader before current readings or consumption resume.
- Begin a separate consumption segment after the format is rebound; do not silently carry an old model's consumption anchor forward.


## 0.2.0-dev19 (local candidate)

- Keep the unchecked camera status readable in the compact Auto layout.
- Explain image-control availability in Settings and link to the camera website when needed.
- Label MQTT output correctly and show Off when publication is disabled.
- Load the notification script once.

## 0.2.0-dev18 (local candidate)

- Keep connection failures on the visible form instead of stacking global and setup errors.
- Cancel pending capture reviews when leaving for setup; preserve unsaved review and configuration drafts.
- Retain typed dial names and valid coordinates immediately, including when switching editor modes before blur.
- Show missing revolution values inline and focus the field without a browser validation popup.
- Keep failed loads from advancing setup and show unavailable MQTT status after an app outage.
- Keep browser route fragments separate from page IDs so navigation opens at the top without anchor jumps.

## 0.2.0-dev17 (local candidate)

- Start setup with gas, water or electric meter type and supported units.
- Keep existing readings in their saved units until an explicit new number format is applied. A unit change requires entering each dial value again.
- Store meter choices independently of images and calibration; preserve invalid files before replacement and reject stale saves.
- Keep the first step compact on mobile and desktop, with one error and a reload action after a failed request.

## 0.2.0-dev16 (local candidate)

- Keep the manual-review photo visible while scrolling phone dial inputs.
- Widen position fields so the Unknown placeholder fits on narrow screens.
- Preserve the dev15 recognition, framing and persistence behavior.

## 0.2.0-dev15 (local candidate)

- Add immediate crop, rotation and straightening, saved with Next.
- Keep original images and source calibration unchanged by framing.
- Use the framing map for alignment, dial placement and number-format previews.
- Keep crop handles anchored, enlarge touch targets and follow rotated resize cursors.
- Fit the desktop editor in one pane and keep mobile toolbars within the screen.

## 0.2.0-dev14 (local candidate)

- Auto chooses light intensity and exposure with gain held at zero, using at most eight temporary pictures. Keep the camera model visible and collapse manual controls. The preference survives app restart independently of the sensor's exposure/gain switches.
- Require the camera's temporary-capture contract. Check request, image, time, orientation and restoration receipts; never fall back to older capture APIs. Block captures after an uncertain operation, including across app restart, until saved settings are explicitly reactivated and verified.
- Save the selected light/exposure pair once, activate both without restarting, and take a normal reference picture. Reject an unusable final picture while keeping the current reference. After a flip, require a new reference and saved calibration before scheduled capture.
- Keep original trial JPEGs and their hashes in a bounded separate archive. Trials never enter readings or training. Picture statistics describe image quality, not recognition accuracy or measured sensor noise.
- Show progress inside the image and offer a saved-settings reload after failures. Camera startup recovery and physical light/sensor behavior remain unverified; this candidate is undeployed.

## 0.2.0-dev13 (local candidate)

- Add saved exposure, gain and flip controls to Image when the camera advertises the matching activation contract. Keep the camera model visible; automatic exposure/gain mode hides manual controls and brightness.
- Keep edits local until an explicit picture or activation request. Apply lighting and image choices in order, carry only verified matching revisions between them, and preserve drafts during repeated status polls. Unchanged choices do not write to SD.
- Persist uncertain activation and block captures across restart. Require a verified orientation receipt, new reference and saved calibration after a flip before scheduled capture can resume. Preview flips immediately relative to a proven camera picture; do not guess the orientation of uploaded images.
- Keep a stale picture dimmed with one centered capture button. Capture masking stays inside the image. Use compact controls with accessible names and a pinned image on mobile.
- Shorten temporary reference filenames so valid Windows data paths do not fail at the ordinary filename-length limit.
- Models, native reading/accounting libraries and saved calculation assumptions are unchanged. This candidate is undeployed; matching camera firmware and physical behavior require separate validation and approval. Automatic exposure/gain is not automatic lighting calibration.

## 0.2.0-dev12 (review candidate)

- Add optional original-image archives to SMB/NFS shares mounted by Home Assistant under /media. Keep local app storage as the default and preserve all local images.
- Run NAS filesystem work in a separate, bounded process. Keep a durable capture-event cursor, verify file/hash readback, reuse interrupted staging files and retain duplicate acquisition events without duplicating JPEG objects.
- Preserve capture timestamps and monotonic-clock provenance. Exclude credentials, model estimates and labels; do not admit archive images to training or count them as verified accuracy.
- Add compact Data controls, copy counts, readable failures and explicit retries. Save through Next with optimistic revision checks; status polling retains unsaved edits and validation errors.
- Keep the current setup tab visible when switching screen sizes. Drain small rejected POST bodies briefly so an access rejection does not appear as a connection reset.
- Request the media directory mapping for the app. Do not add Supervisor administration privileges, SMB credentials, an external receiver or new dependencies.
- Models, recognition, physical calculations and camera configuration are unchanged. Real SMB/NFS operation remains unverified; this candidate is not deployed.

## 0.2.0-dev11 (review candidate)

- Add a separate Lighting step with explicit camera-settings loading, built-in or addressable lighting, GPIO, pixel format/count, dedicated white, RGB and custom channel mix. Brightness belongs on Image and scales the selected light.
- Use the installed camera's existing conflict-protected save and lighting-activation handlers. Preserve unrelated configuration bytes; unchanged choices cause no SD write. Lighting applies without restarting the camera.
- Persist uncertain write/activation state and block new captures until saved choices are loaded and explicitly activated. Do not retry uncertain writes automatically. Camera credentials and raw configuration are not sent to the browser or stored in the intent record.
- Gray a stale photo and highlight its centered Take picture button; retain an unchanged reference. Keep camera model visible and custom RGBW mix free of the RGB picker. Hide the mobile step-strip scrollbar without causing page overflow.
- Preserve models, native cores, calculations, calibration, number format and application options. Exposure, gain and sensor orientation still use the camera website. Physical lighting behavior has not been verified by this candidate.

## 0.2.0-dev10 (review candidate)

- Add a compact guided setup: Image, Alignment, Dials, Number format, Data and Finish. Next validates and applies the relevant step; finishing does not restart the camera or enable capture/MQTT.
- Separate the three alignment markers from dial editing. Keep all dials in one selector with X/Y controls, proportion locking, rim landmarks and a separate needle pivot.
- Keep the reference beside controls on desktop and visible while scrolling controls on mobile. Add grid, zoom and fit icons without altering image pixels.
- Reuse an unchanged reference and calibration. A different reference requires fresh geometry. Failed image loads retain the old reference.
- Add explicit, asynchronous camera checks and setup photos. Page navigation never probes or captures from the camera. Verified photos become reference candidates, not reading events or training labels.
- Add Settings for camera status, local HA storage and diagnostics. Camera setting controls remained on the camera website in this version; dev11 integrates the existing lighting handlers.
- Fix stale navigation, legacy calibration bookmarks and selection resets. Use one specific setup error instead of duplicate notifications.
- Preserve trained models, native cores, physical calculation, saved reader assumptions and application options.


## 0.2.0-dev9 (review candidate)

- Remove position-error controls from Number format, including Advanced. Editing
  physical dial values preserves saved reader assumptions. New formats retain
  the provisional Â±0.1 default until model/calibration error is validated; this
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
