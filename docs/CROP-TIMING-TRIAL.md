# Crop addressing trial

The crop sampler now computes clamped neighborhood byte offsets once per pixel
and shares them across RGB channels. Double interpolation arithmetic, evaluation
order, clipping and pixel conversion are unchanged.

Sixteen golden crop comparisons and 108 full preprocessing cases retained exact
byte parity. The ESP32 build passed. Test-board OTA installed bundle
`84fbff9e99d3149257bc5885abbe0504fc2bd18c1daa85e95ee65955e68a0bb6`,
preserving configuration and website credentials.

The first saved-JPEG benchmark lost its volatile result and ended at `not_run`;
it is retained as a failed observation. A later passive USB recording showed a
power-on/reset-button startup, not a captured panic. This does not establish the
cause of the earlier interruption. The runner now persists preflight and terminal
boot identities rather than assuming a lost result is successful completion.

After reconnection, one instrumented run completed all six dials with exact
feature/output parity in **22.065452 seconds**, against a previous single-run
measurement of **22.148979 seconds**. Boot identity and configuration remained
unchanged. This small difference does not establish a meaningful speedup.

These are saved-image processing measurements, excluding camera acquisition,
publication and sustained cadence. They do not prove independent reading accuracy
or the 30-second live target. Private raw evidence is under
`needle-training/firmware-port-tests/warp-offset-instrumented-02-20260923` in the
development workspace; no private image is included in this repository.
