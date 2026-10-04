# Development status - October 4, 2026

Dev27 is an unpublished local candidate based on dev26. It adds masked numerical
accounting and an explicit development controller that records each capture's
full or last-two recognition request before inference. Identical images retain
separate capture timing, decisions and accounting events. Historical trial
results recover those bindings without acquiring pictures or invoking models.

Ordinary service startup still uses full recognition. The development opt-in
does not enable capture, MQTT or archiving and does not change automatic capture
cadence. Full alignment and preprocessing remain. Model weights, calibration,
dependencies, option defaults and firmware are unchanged.

Local synthetic/native checks establish persistence, replay, binding and selected
network-call behavior. They do not establish recognition accuracy, real processing
savings, safe physical capture cadence or device recovery. Linux container and
exact-head CI evidence are required before proposing a live installation.

Phase 2 remains open: independent recognition accuracy and physical cumulative
accounting still need validation. Camera firmware/recovery, sustained cadence,
storage interruption, UI/setup and clean installation remain later phases.
No production reflash is authorized by this candidate.
