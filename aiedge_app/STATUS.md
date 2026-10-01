# Optional network archive candidate - October 1, 2026

The installed checkpoint is dev11. Its approved update preserved the reference,
six-dial calibration, physical format, pipeline, four images and reviews. Capture,
MQTT and automatic updates remain off. Its camera URL is configured and a read-only
lighting load verified an OV2640 and 19 SK6812 RGBW pixels. Physical lighting
activation and reading accuracy remain unverified.

Dev12 is a separate review candidate. It adds optional SMB/NFS copies through
Home Assistant network storage, default off. It requires the media directory
mapping. The Data step explains how to mount a share and queues stored/new
capture events only after saving. Local images are never removed. Credentials
stay with Home Assistant; no separate receiver or SMB client is added.

NAS filesystem work runs in one isolated child with a 15-second deadline,
parent-death termination and a process lock retained across a blocked syscall.
Acknowledgements require exact hash/readback evidence. Lost acknowledgements
recheck the same manifest; a corrupt image or conflicting remote file blocks
progress. Transient failures retry with bounded backoff. All queued work is
represented by the existing capture ledger and a separate durable cursor.

Windows validation: 327 checks passed, including protected saved-image replay;
two Linux filesystem/process checks and the Linux packaged-runtime check are
explicitly skipped. All 74 browser-logic checks passed. The required Linux job
must exercise those checks before this head is eligible for deployment.

Local Chrome QA covered the normal desktop viewport and 390/320 px mobile
widths, light/dark themes, form validation, Next saving, and current-step visibility.
No horizontal page overflow or console errors were observed. Fixtures use saved
images and simulated camera lighting; no camera or NAS request occurred.

Models, native recognition/accounting cores, reader settings, calibration and
number-format identity are unchanged. Archive files remain unchecked and are
excluded from training and accuracy evidence. A real SMB/NFS mount, deployed
copy, sustained capture/MQTT operation, camera exposure controls and tested
firmware recovery remain open. No live update is authorized by this file.
