# Final UI pass - October 2, 2026

Dev19 is a local UI-only candidate based on the deployed dev18 source. The
unchecked camera header and load button fit the compact Auto layout. Settings
distinguishes unchecked controls, available exposure/gain controls, unsupported
firmware and pending recovery. Overview labels MQTT output accurately and
reports disabled output as Off. The notification script is loaded once.

Validation: 425 backend checks pass, including protected saved-image replay;
three Linux-only checks are skipped. All 157 UI checks pass. Browser checks
cover five camera states at 320, 390, 1024 and 1440 px in both themes: 40
combinations with no horizontal overflow, clipped controls or unexpected notices.
Mocked camera metadata is confined to the disposable preview server; camera
actions are disabled there. No real camera or Home Assistant request was made.

Raw reference images, calibration, separate needle pivot, image-edit settings,
meter metadata and physical number format are preserved. Models, native code,
dependencies, app options and permissions are unchanged. Fixture images and
screenshots stay excluded from training. Invented fixture events verify neither
accuracy, physical lighting/exposure nor sustained capture timing.

Dev18 remains installed. Dev19 publication, exact Linux package validation and
approved live verification remain pending. Physical camera recovery and capture
cadence remain separate delivery phases.
