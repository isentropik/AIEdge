# Image-controls candidate - October 1, 2026

Dev13 adds compact Image controls to the separate app candidate. The latest
verified installed checkpoint is dev11. Dev12 network archiving was merged,
but installation remains pending exact approval for writable /media access.
No live HA option, camera setting, firmware or photo changed in this work.

Exposure/gain/orientation edits require a camera advertising the matching
activation contract. Only nine supported saved fields can change; other bytes
remain intact. No-op submissions avoid SD writes. Exact saved/readback hashes
and activation receipts must agree. Uncertain results persist a capture gate
across restart, without blind retries. Verified lighting/image updates share
only a matching baseline revision; independent changes still cause a conflict.

The camera model stays visible. Automatic exposure and gain hides manual fields
and brightness; it delegates AEC/AGC to the sensor and is not automatic lighting
calibration. Slider changes do not capture or write. A stale photo is dimmed with
one centered Take picture button; the busy mask covers only the image. Proven
photo orientation supports immediate flip previews. Uploaded/legacy images have
no guessed orientation. A sensor flip requires a verified photo and new saved
calibration before scheduled capture resumes. Old reference landmarks are cleared.

Windows validation: 347 checks passed; two Linux filesystem/process checks and
the Linux packaged-runtime check are explicitly skipped. All 96 Node UI checks
passed. Local Chrome covered the normal desktop viewport and 390/320 px mobile
widths, both themes, keyboard controls, pinned mobile image, simultaneous lighting
and exposure edits, exact orientation receipts, single errors and current-step
navigation. No page-width overflow or browser console errors were observed.
Camera/network behavior in browser QA is simulated using a protected saved image.

Models, native recognition/accounting cores and saved reader assumptions are
unchanged. Archived-image replay is behavior validation, not accuracy evidence.
Linux packaged validation for this candidate, physical dimming/sensor behavior,
automatic lighting calibration, other sensor tunables and crop/rotation remain
open. A separately reviewed firmware build must satisfy tested production startup
recovery before any flash. This candidate is not deployed.
