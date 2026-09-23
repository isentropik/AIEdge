# Cumulative consumption checks

The secondary wheel represents 5 cubic feet per revolution. The last main dial
represents 1,000 cubic feet per revolution: 20 secondary revolutions per numbered
main-dial step, or 200 per full main-dial revolution. Raw positions stay separate
from consumption. Monotonicity applies to cumulative volume, not dial positions.

## Consecutive turn tracking

A September 23 regression exposed loss of information: the cumulative calculation
compared only the anchor and current frame, discarding uniquely established turn
counts between consecutive frames. Over a longer interval it could therefore
report ambiguity even though the intervening observations resolved the turns.

The correction retains discrete turn offsets only when the interval is unique
under the configured error and maximum-flow assumptions. Volume still comes from
the anchor-to-current phase difference plus those turns; positive noisy deltas
are never summed. Anchor/main-register bounds must also agree. An ambiguous gap
invalidates the tracked path. A later unique anchor-to-current solution can
reestablish it. Rejected observations do not advance the reference.

These assumptions are not accuracy measurements. The current firmware wiring
uses default errors and no maximum-flow bound, so it can still report ambiguous
turn counts. The regression supplies an explicit synthetic bound; it does not
justify applying that bound to a household meter.

## Tests and limits

Run `python tools/bundle-tests/test_meter_cumulative.py` with `ziglang` installed.
It checks 40 consecutive unique intervals, a later ambiguous gap, 2,000 stationary
wrap-boundary observations, 2,000 stationary jitter observations, 500 sub-noise
increments, a 20-turn gap with exact main readings, backward drift, and restart.
These are algebraic fixtures, not human-confirmed image labels or hardware tests.

Checkpoint reconstruction preserves the saved lower bound. It does not persist
the complete in-memory turn path, so historical upper bounds can widen and an
estimate can become unavailable after restart. New-boot intervals remain explicit
gaps; the code does not manufacture elapsed time or hidden revolutions.

## Test-board integration

The correction was installed by authenticated compressed OTA on September 23.
Bundle `f17e155012edc3e9b5b9c1adb2dfafb501129653d9f909552e966a687e51d7a8`
booted and verified its runtime files. Configuration and password were preserved.
All six frozen inference vectors matched every expected output byte. The diagnostic
left meter accounting and configuration unchanged. Nine representative website
routes, including configuration, cached images, logs and accounting, returned 401
without credentials. This is endpoint denial evidence, not an exhaustive security
audit or proof of encrypted transport.

Private records are in `aiedge-turn-tracking-candidate/ota/result.json` and
`aiedge-turn-tracking-candidate/runtime-verification/result.json` under the workspace
firmware-port-tests directory. The turn sequences themselves were tested on the
host; this integration check did not feed a physical meter sequence through ESP32
accounting. Real-image validation remains open. These results do not establish
reading accuracy, a lifetime total, or the 30-second target.
