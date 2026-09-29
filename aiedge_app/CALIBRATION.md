# Runtime calibration

The server accepts an explicit `--calibration-file PATH` alongside `--models PATH`
and `--native-library PATH`. `--calibration-profile frozen-gas-six-dial-v1` remains
available for historical replay. These options are mutually exclusive. Neither is
auto-selected from image dimensions. The native bridge now requires ABI 2.

JSON version 1 contains:
- `image_size`: currently `[640, 480]`.
- `reference_sha256`: identity of the reference image that defines this geometry.
- `markers`: exactly three objects with `box` `[x,y,width,height]`, canonical
  `target` `[x,y]`, base64 grayscale `pixels`, and their `sha256`.
- `dials`: 1-32 objects with unique `name`, `crop` `[x,y,width,height]`,
  `sampling_anchor` `[x,y]`, nine-number inverse homography, two-number fixed
  `pivot`, `direction` (`cw`/`ccw`) and explicit model route (`main`/`secondary`).
  Model route names refer to the two existing trained artifacts; they do not assign
  accounting roles or prove suitability for an unfamiliar needle design.

The inverse homography maps the normalized dial plane into crop pixels. The pivot
is independently calibrated in that plane; it is not inferred from the crop center.
Sampling anchors preserve sparse sampling phase when moving a crop in the same
reference plane. A crop alone does not establish this geometry.

Import verifies finite numbers, unique names, marker bytes/hashes, marker placement,
nondegenerate targets, crop bounds, nonsingular transforms, and the full sampling
region. The native handle owns validated copies. Invalid candidates cannot modify
an active profile. This validates geometry numerically, not recognition accuracy.

Current bounds inherited from preprocessing: marker sizes 8-128 pixels, dial crops
at most 148x148, 640x480 frames. Setup must expose these limits and reject unsupported
inputs. The format does not yet support arbitrary camera resolution, unreviewed
automatic pivot fitting, or importing another model tensor contract.

The pipeline fingerprint includes the calibration identity, model hashes, native
library hash, reader source and inference/decoder dependency versions. Stored
results from a previous fingerprint are not reused for a new profile.

Private reference pixels and meter profiles remain local test artifacts; do not
publish them as part of a generic app release.

## Building and saving a profile

`calibration_builder.build(reference_bytes, design)` consumes three marker boxes
and a dial list. Each dial supplies name, model, direction, crop, four `rim_points`
in full-image coordinates, and a separate `needle_pivot`. Rim points run clockwise
from the dial's zero position at quarter-turn intervals. The builder solves the
projective mapping and transforms the independently supplied pivot; it does not
infer the pivot from the dial outline. The native profile then validates sampling.

`Setup` stores reference bytes by hash, validates a complete reader and requires a
successful reference preflight before saving. An expected revision prevents a stale
editor overwriting a newer profile. Atomic replacement occurs under the recognition
frame lock; rejected candidates and failed writes leave the active reader unchanged.
Reference files are not captures, training labels, or accuracy evidence. Creation of
a usable geometry does not prove that existing models generalize to a new meter.
The local Calibration editor and setup HTTP endpoints now use this path. Camera
connection and lighting setup remain separate pending stages. Number format is now
available as a separate page. The setup editor and physical-reading calculation
currently support at most 16 dials, although the low-level geometry ABI accepts 32.
