# Optional image archive tools

See [the setup guide](../../docs/IMAGE-ARCHIVE.md). Python 3.10 or newer is required.
The receiver and setup generator use only Python's standard library. No cloud
account or storage server is needed unless you choose to enable archival.

Run the receiver tests from this directory:

```sh
python -m pip install -r requirements-test.txt
python -m unittest discover -p "test_*.py"
```

Tests create temporary folders, certificates and loopback listeners. They do not
contact a meter or external server. `cryptography` is a test-only dependency.
Run the tests here so imports use the distributed implementation, not another
workspace copy. The setup generator creates both the current unified settings
file and legacy reference files, with matching receiver credentials. It starts
no service and contacts no device.
Do not place generated tokens or private keys in this repository.


## Check collected images before review

Run the read-only audit on the receiver's storage folder:

```sh
python audit_image_archive.py /path/to/archive
```

It prints a JSON report: checked records, valid records, corrupt or missing
objects, exact repeated image hashes, unknown UTC timestamps, and groups with
matching device, firmware, model, calibration and camera settings identities.
A changed group needs review before mixing images into a training dataset.
The audit verifies image bytes and the saved settings descriptor; it does not
validate the actual model or calibration files from their recorded hashes alone.

Exit status is 0 when all checked records pass, 1 when records fail, and 2 for an
invalid or inaccessible archive folder. An empty folder reports zero checked
records; this is not evidence that uploads worked. Concurrent uploads may require
a later audit. Only capture records and referenced files are checked; orphan and
interrupted files are left untouched.

This does not label images, detect visually similar images, assign training/test
splits, repair files or delete anything. Original archive records must remain
unreviewed and ineligible for training. Keep human labels and split decisions in
separate review records, with their source image hashes.

## Duplicate upload checks

Retries compare existing image, capture-record and settings files using a bounded
read (the expected size plus one byte). Oversized or different existing files
are rejected as conflicts and left unchanged. This also bounds publication
readback; it does not repair damaged archives.

## Prepare images for training review

After an archive passes the integrity audit, create a separate review manifest:

```sh
python prepare_training_review.py /path/to/archive --protected-hashes /path/to/protected.json --output /path/to/review.json
```

The protection file must contain your existing held-out image hashes and hashes
of related images you have already decided to protect:

```json
{"version": 1, "image_sha256s": ["REPLACE_WITH_A_REAL_64_CHARACTER_LOWERCASE_SHA256"]}
```

The placeholder above is deliberately invalid. Use actual image hashes, not
filenames or predicted readings. An explicit empty list is appropriate only
when starting a new dataset with no protected images. The tool cannot discover
held-out data elsewhere on your computer. Do not use an empty list to bypass an
existing split. Missing or malformed protection files stop preparation.

The output groups images by device, firmware, model, calibration and capture
settings. Exact repeated images share one review entry while retaining all
capture identities and timestamps. Images recorded under conflicting settings
are excluded for review rather than assigned to an arbitrary group. Protected
hashes are excluded entirely. Any corrupt archive record stops preparation.

This JSON file is the starting inventory for review, not a visual labelling UI
or a training dataset. Labels remain null, splits remain unassigned, and training
eligibility stays false. Visual near-duplicates still need split review before training; the temporal
exclusion described below does not identify all similar images. Unknown capture UTC
stays unknown. Do not compare monotonic capture times across device boots.

The command never modifies archive records, overwrites an existing output, or
writes the review inside the archive. Recheck hashes when consuming the images,
since the manifest describes the archive at the time it was read.

## Open a full-image review gallery

The optional gallery needs Pillow on the computer preparing the review. The
receiver itself still uses only Python's standard library.

```sh
python -m pip install -r requirements-review.txt
python build_review_gallery.py /path/to/archive --protected-hashes /path/to/protected.json --group GROUP_ID --output /path/to/new-gallery
```

Replace `GROUP_ID` with the full `group_id` from a prepared review manifest.
Open `index.html` in the new folder. Keep the image files beside it. The gallery
contains private copies of the original images and capture identities; store
or share that folder only where you intend those images to be accessible.
It starts no server and uploads nothing.

The gallery shows six unique images by default, or up to twelve with `--limit`.
Use `--offset 6` and a new output folder for the next batch. Ordering is by image
hash, not capture time. Tap an image to open its original size. System, light and
dark themes are available. Capture details preserve unknown UTC and boot identity.

Every export reruns the integrity and protection checks, verifies each selected
image hash, and decodes JPEG/PNG files before writing the gallery. Images must be
single frames no larger than two million pixels. Original bytes are copied
without resizing or recompression. Existing output folders are never overwritten.
If disk writing fails, leave the partial folder for inspection and retry into a
new folder; it is not a completed gallery until `index.html` exists.

This is a read-only full-image review, not a dial-labelling interface. It has no
needle overlay, suggested readings, label submission or training activation.
Calibration-aware crop overlays remain future work. Separate human-label records
can now be saved with the command below. Automated export checks pass; browser layout verification is pending.

## Protect captures near held-out images

Both review commands default to a five-minute exclusion window on either side
of each protected capture. A different image hash is excluded when any of its
capture records lies within that interval on the same device and boot. All
occurrences of that image are then excluded, including later exact duplicates.
The tool records the matched capture IDs and time difference in the inventory.
It does not expand the window recursively from excluded neighbors.

Use `--protect-window-seconds N` on both commands to choose an interval from 0
to 86,400 seconds; 0 explicitly disables temporal exclusion. The default is a
conservative review policy, not a measured independence threshold. Keep the
same option when preparing a manifest and exporting its gallery.

The tool never compares monotonic times across boots or devices. Protected
hashes absent from the archive remain hash-protected, but their time neighbors
cannot be found; the output and gallery report this gap. Similar stationary
images outside the interval, or across restarts, may still leak information
between training and evaluation. Review those separately before assigning any
split. No reviewed image is automatically made eligible for training.


## Save human readings separately

`record_review_labels.py` records readings supplied by a person. It does not
read needles automatically, modify the gallery, or start training. Keep the
original gallery and archive. Use a new output filename for each revision.

Prepare an `answers.json` file like this, replacing the hash placeholders with
the actual values. `review_sha256` is the SHA-256 of the gallery's `review.json`
file; each image hash is listed inside that file. A reviewer nickname is enough.

```json
{
  "version": 1,
  "review_sha256": "REPLACE_WITH_REVIEW_FILE_SHA256",
  "reviewer": "your nickname",
  "method": "independent_reading",
  "dials": ["main_10k", "main_1k"],
  "images": [
    {
      "image_sha256": "REPLACE_WITH_IMAGE_SHA256",
      "readings": {"main_10k": 5.3, "main_1k": null}
    }
  ]
}
```

These dial names and numbers are examples, not suggested labels. Use names that
match your calibration. Every submitted image must have an entry for every
declared dial. Use `null` when you cannot read one. Positions use the dial's own
numbering on a 0–10 scale, with 0 included and 10 excluded; these are not physical
volume or electricity units. Normalize a secondary 0–5 wheel to that scale before
recording it. Never use filename predictions as labels.

Set `method` to `confirmation_of_shown_estimate` if the reviewer saw and accepted
a model estimate. This preserves the distinction from an independent reading.
The tool records that statement; it cannot verify who supplied it or its accuracy.

```sh
python record_review_labels.py /path/to/archive --review /path/to/gallery/review.json --answers /path/to/answers.json --protected-hashes /path/to/protected.json --output /path/to/new-labels.json
```

The output must be outside both the archive and original gallery. The command
checks the exact review hash, audits the current archive, and reapplies current
held-out and temporal protection. Changed capture provenance, protected images,
duplicate submissions, invalid values and existing outputs are rejected. A
nonempty subset of the gallery may be submitted; omitted images remain untouched.

Saved records include capture provenance, review/submission hashes, review method,
and unknown readings. They stay `split: unassigned` and `training_eligible: false`.
Before training, independently check dial mapping, near-duplicates and dataset
splits. Human confirmation alone does not grant training eligibility.


### Windows network shares

The receiver can write to a UNC folder using its Windows account's existing
share access. The ESP32 still uploads over HTTPS; it does not connect to SMB.
A Windows service may need its own share permissions even when your interactive
account can open the folder. Do not put share passwords in command-line arguments.

Before starting uploads, run:

```powershell
python probe_archive_storage.py '\\server\share\aiedge'
```

This creates a new test subfolder and leaves existing files alone. Keep the
result for troubleshooting. The report includes elapsed time, a failed stage and
OS error codes when applicable. It also tests four competing synthetic writes:
exactly one must succeed, and retries must preserve its bytes. A transient SMB
storage error is recorded even when the conflict/retry checks pass. This is a
compatibility check, not a throughput benchmark. Windows publishes a flushed temporary file using
non-replacing rename; other systems use hard links. There is no copy/overwrite
fallback. Windows rename refuses an existing destination ([Python documentation](https://docs.python.org/3/library/os.html#os.rename)). Some SMB servers report an
access-denied error under contention; that remains a storage failure without a
success receipt. A retry checks the original file and accepts only identical data.

A real Windows-to-SMB test on September 24 passed creation, readback, identical
retry and conflict protection. Eight competing writes produced one intact winner;
conflicts and a storage error did not overwrite it, and subsequent retries behaved
correctly. This verifies tested file operations, not power-loss durability or a
complete ESP32-to-share upload. Windows directory fsync is not provided here.

A separate synthetic JPEG passed authenticated, certificate-verified HTTPS upload
through a temporary loopback receiver into the SMB share. Settings and capture
hashes, byte readback, duplicate retry and the integrity audit passed. The receiver
used its normal 15-second request timeout; the one-second unit-test timeout was
too short for this network-storage test. No real camera image was transferred,
no device settings changed, and the temporary receiver was stopped. This does
not yet verify ESP32-to-share delivery or sustained upload throughput.


## Check linked main-dial labels

For a meter whose adjacent main dials have a 10:1 ratio, you can check a saved
human-label record before considering any training use:

```sh
python audit_linked_labels.py labels.json --sequence main_10000k main_1000k main_100k main_10k main_1k --error 0.1 --output linked-review.json
```

Use your actual dial names, highest place value first. Select only adjacent main
dials with that ratio. Do not include the five-cubic-foot secondary wheel in this
sequence. Each row must describe the same full image; values must already follow
each dial's numbering direction. Unknown values stay unknown.

The error argument is your explicit per-dial assumption on the 0–10 scale, not a
measured accuracy. The example allows 0.1 per dial and a combined 0.11 pair bound.
A report can say **review**, **consistent with assumption**, or **unknown**. Even
consistent labels can both be wrong. Disagreement may reflect approximate labels,
calibration or pointer offsets; never automatically correct labels to make them
agree. The tool preserves the labels, records their file hash and review method,
and does not change splits or admit images to training. The output must be a new
file. Existing split and near-duplicate protections still apply.


### Blank-image warnings

The review gallery warns when an image is exactly uniform or fully transparent.
Keep its readings unknown; the original file and capture details remain available
for diagnosis. Warnings are stored separately from label rows in `review.json`.
This does not delete captures, change training eligibility, or alter held-out
protection. A picture without a warning may still have glare, poor focus, wrong
alignment or an unreadable needle; this check is not an accuracy score.
