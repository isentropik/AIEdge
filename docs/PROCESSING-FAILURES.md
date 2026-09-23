# When a processing cycle fails

The controller stops the current cycle when a stage reports failure. It does
not retry that stage in place or reboot because a processing stage failed.
The next scheduled cycle, or a later manual cycle, can try again from the start.

The status identifies capture, alignment, recognition and MQTT failures.
Other stage failures report `Processing failed`; the device log identifies
the stage. A failed cycle does not report `Flow finished`, and later stages
in that cycle are not called.

This matters because alignment can change the current image, and later stages
can write data or contact another service. Repeating them against the same frame
could repeat those changes. Stopping does not undo work a stage completed before
reporting failure. It also does not guarantee delivery to an unavailable broker
or storage service.

This policy covers the normal full-cycle controller. It does not claim that
every driver, startup path or manually invoked individual stage is reboot-free.

## Validation and release status

The actual controller function passed host regressions for capture, analog,
digital and MQTT failures, plus alignment, post-processing, export and unknown
stage failures in three positions. Tests verify one call to the failing stage,
no downstream calls, no controller reboot, no success message, and successful
execution of a later cycle. Stage and MQTT implementations are substitutes in
these tests. Existing scheduling and telemetry checks also pass.

At the time of this change, this policy has not yet been exercised through a
deliberate hardware fault or included in a public installer release. Full live
capture cadence and real reading accuracy remain separate validation work.
