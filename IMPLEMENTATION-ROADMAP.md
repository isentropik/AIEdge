# Replacement meter firmware: remaining delivery work

September 22 local development. Goal incomplete. No firmware, model or configuration
has been deployed by this work. A host test or ESP32 build is not installed-device evidence.

## Implemented locally

- Frozen analog model with alignment, fixed geometry and visibility rejection;
  numerical preprocessing parity and 27 confirmed crop checks, with limited operating
  positions and human-label uncertainty. No new accuracy samples from repeated tests.
- Versioned OTA bundle verification/staging, explicit install UI, per-app asset index,
  SDK boot-selection readback and guarded post-boot software acceptance lifecycle.
  Current SDK rollback remains disabled; installed bootloader compatibility is unknown.
- Configured RGB/RGBW lighting, master intensity paths and streaming controls.
- Capture timestamp provenance, bounded cycle scheduling, boot-identified telemetry,
  offline trial collection/analysis, manually refreshed diagnostics page.
- Bounded archive queue/spool, TLS receiver, offline server IP/hostname and folder
  setup, same-configuration resume. Destination changes still need controlled restart.
- Rollover-aware accounting with explicit bounds, durable completed segments and
  bounded history inspection. Unresolved restart gaps remain unresolved. Optional
  nonretained MQTT snapshot leaves legacy entities/units unchanged and defaults off.

## Remaining implementation and integration

- Validate archive credentials/trust and provision the user-selected server/folder;
  test actual ESP32 TLS, SD interruption recovery, resource limits and archive misses.
- Finish controlled configuration/reload workflows where safe. Verify UI changes
  under real inference/streaming load and rendered browser behavior.
- Extend restart-gap reconciliation only where observations support unique physical
  volume; never infer missing wheel turns from endpoint positions alone. Covered
  history is not a lifetime total. Establish defensible physical bounds before
  treating conditional interval estimates as actual consumption.
- OTA needs durable recovery/status handling and interrupted-update testing on
  suitable hardware. Host SDK simulations cannot prove bootloader recovery.

## Required hardware and model evidence

- Establish physical recovery access, exact backup/recovery artifacts, installed
  partition/bootloader compatibility and reviewed installation scope before flashing.
- Run frozen-vector inference parity on ESP32, then labeled final-lighting full-frame
  validation. Preserve held-out data, hashes and near-duplicate protection.
- Measure sustained capture-to-publication timing toward 30 seconds, valid readings,
  missed cycles, heap/PSRAM/stack margins and UI/network latency, including archival.
- Verify all 19 RGBW pixels, dedicated white channel and intensity behavior physically.
- Verify MQTT receipt, actual units/freshness and any reviewed HA integration separately.

Use each candidate's manifest, logs and review record for its exact evidence. Older
candidates do not contain later changes. Packaging is local only and never approval
to flash. The full objective remains open until implementation and scoped hardware
acceptance both succeed.
