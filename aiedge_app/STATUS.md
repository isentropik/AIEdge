# Auto capture candidate - October 2, 2026

Dev14 connects scene-aware Auto to the Image step. This is a local candidate;
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
setup. Other sensor tunables and whole-frame crop/rotation remain outside the
current camera contract.
