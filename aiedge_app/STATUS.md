# Meter-setup candidate - October 2, 2026

Local dev17 adds Meter and units before Lighting, making eight setup steps.
Gas supports ft³/m³; Water also supports litres and US gallons; Electric supports
kWh. Existing units suggest a choice without inferring the meter type. Meter
metadata has its own conflict-checked, recoverable app file and needs no camera,
reference image or dial calibration to save.

Changing units does not alter the active number format, stored readings or
calibration. Number format clears physical dial values and the optional rate
when the chosen units differ, and requires an explicit replacement save. The
server rejects a stale format save in the wrong selected units. The same-unit
path preserves existing values and unchanged Next does not invalidate drafts.
Remaining full-route failure-state review and live deployment are pending.

Local dev16 widens manual-review fields and keeps the photo visible while
scrolling phone controls. Saved-image browser checks passed at 320 px in both
themes; all 123 UI regressions passed. The dev15 base passed
417 Windows backend checks, 414 Linux package/backend checks and 123 UI checks.
Only presentation and version/documentation files change in this candidate;
recognition, calculations and stored-data contracts remain intact.

Dev15 adds crop, quarter-turn rotation and straightening to the scene-aware
Auto candidate. Framing updates immediately from the existing image. Next saves
it in app storage without another photo or camera configuration write. Alignment,
dials and the Number format preview use the same source-coordinate mapping.
The original image, native sampling pixels, calibration and separate fixed needle
pivot remain intact. Crops that hide saved markers or dials cannot be activated.
Corner dragging uses a fixed map and anchored opposite corner; touch targets are
larger. Desktop framing stays in one pane; mobile has no horizontal overflow.

This is a local candidate;
it has not changed the installed HA app, camera firmware, settings or photos.
The previously verified live app checkpoint is dev12, recorded separately.

Auto is a durable app preference rather than an alias for sensor AEC/AGC. It hides
manual controls and brightness, keeps the camera type visible, and remains selected
after choosing a fixed exposure. An explicit Take picture action tests a bounded
set of light/exposure choices with gain zero. The selected light and image settings
are saved together once, activated with exact readback, then checked with a normal
reference picture. An unusable final picture leaves the current reference intact.

Firmware must advertise the exact temporary-capture contract. Each trial uses
RAM-only settings and proves restoration before the response. Lost, invalid or
unverified replies leave a durable capture block across app restart. Loading
settings or disabling Auto does not clear it. Explicit recovery activates only a
known saved revision on the same camera; it does not retry a probe or uncertain
save. Orientation changes retain the separate reference/calibration guard.

Trial JPEGs, hashes and redacted metadata remain outside reading history under
`auto-trials`. Storage is bounded, with no automatic deletion. The quality scorer
is a heuristic, not a measurement of sensor noise or recognition accuracy.
Models, native recognition/accounting code and saved meter math are unchanged.

Regression checks use loopback camera substitutes and protected archived images.
Browser checks cover desktop and 320 px mobile layouts, Auto/manual mode,
progress inside the image and retention of the final reference. Exact counts,
input hashes, retained failures and screenshots belong to the candidate's
validation artifacts, not a live accuracy claim.

Linux packaged validation, physical light/exposure behavior and exact-build
production startup/recovery validation remain open. No firmware update belongs
to this app candidate. Scheduled capture, MQTT and archiving are not enabled by
setup. Other sensor tunables remain outside the camera contract. App framing
does not change sensor orientation, resolution or JPEG settings.
