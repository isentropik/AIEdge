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
