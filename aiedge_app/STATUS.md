# Development status - October 4, 2026

Dev28 is an unpublished local candidate based on the released dev27. Dev27 added masked numerical
accounting and an explicit development controller that records each capture's
full or last-two recognition request before inference. Identical images retain
separate capture timing, decisions and accounting events. Historical trial
results recover those bindings without acquiring pictures or invoking models.

Ordinary service startup still uses full recognition. The development opt-in
does not enable capture, MQTT or archiving and does not change automatic capture
cadence. Dev28 retains full alignment and quality checks while allowing runtime
profiles to omit crop and feature work for unrequested dials. Omitted results
are unavailable and their caches are invalidated. Disabled reuse and built-in
fixed profiles retain full preparation. Model weights, calibration,
dependencies, option defaults and firmware are unchanged.

Local synthetic/native checks establish persistence, replay, binding and selected
network-call behavior. One protected 27-frame Windows diagnostic measured 40.6%
less native preparation time than the preceding full path, with identical selected
features and quality states. This excludes decoding, models and acquisition and
does not establish repeatable or installed-system savings. Recognition accuracy,
safe physical capture cadence and device recovery remain unverified. Linux container and
exact-head CI evidence are required before proposing a live installation.

Phase 2 remains open: independent recognition accuracy and physical cumulative
accounting still need validation. Camera firmware/recovery, sustained cadence,
storage interruption, UI/setup and clean installation remain later phases.
No production reflash is authorized by this candidate.
