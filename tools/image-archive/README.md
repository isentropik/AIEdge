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
eligibility stays false. Near-duplicates and adjacent captures still need split
review before training; exact hashes cannot identify those. Unknown capture UTC
stays unknown. Do not compare monotonic capture times across device boots.

The command never modifies archive records, overwrites an existing output, or
writes the review inside the archive. Recheck hashes when consuming the images,
since the manifest describes the archive at the time it was read.
