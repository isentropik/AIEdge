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
