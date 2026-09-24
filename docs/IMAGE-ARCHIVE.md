# Save images to your storage server

Image archiving is optional and off by default. It saves original captures for
later review; it never labels them or adds them to training automatically.

**Development status:** the test ESP32 has delivered a queued image over HTTPS,
verified its hashes, and recovered settings after simulated interrupted writes.
The web settings form is installed on that test board. Physical power-loss
recovery, sustained recognition/upload performance and broader NAS compatibility
remain unverified. The published web-installer binary does not yet include this
feature. You can leave archiving disabled and use AIEdge normally.

## What you need

- A computer or NAS that can run Python 3.10 or newer.
- Its IP address or a hostname the ESP32 can resolve, such as `storage.example.net`.
- An absolute folder path on that server, such as `/srv/meter-images` or
  `D:\MeterImages`. The receiver must be allowed to write there. On Linux, the filesystem must support hard links for publication without
  overwriting captures. Windows uses a same-folder rename that refuses replacement;
  check the actual share with the supplied storage probe.
- An HTTPS certificate and its private key on the server, plus the certificate
  authority (CA) certificate trusted by the meter. The certificate must cover the
  exact hostname or IP you enter. A CA certificate alone does not establish this.

A server name and folder identify the destination, but the server must also run
this receiver. An existing SMB or NFS share alone is not sufficient. The ESP32
sends uploads over HTTPS; it does not mount a network drive.

## Prepare the files

Download this repository, then open a terminal in `tools/image-archive`.
Run the following as one command, replacing every example path and hostname:

```sh
python prepare_archive_setup.py --output archive-setup --host storage.example.net --folder /srv/meter-images --ca-file /path/to/ca.pem --certificate /etc/aiedge/server.pem --private-key /etc/aiedge/server-key.pem --device meter-01
```

On Windows, use absolute Windows paths and quote paths containing spaces.
`--ca-file` is read on the computer running this command. The folder, certificate
and private-key paths refer to the storage server. The command creates files
only: it does not contact a device, start a server or change firewall settings.
It refuses to overwrite an existing output folder.

The generated `archive-setup` folder contains matching server and meter settings,
including a random upload password called a token. Keep it private and out of
Git. On Windows, restrict the folder's Security permissions to the intended user;
file-mode settings alone do not enforce Windows permissions.

## Start the receiver

1. Review `server/receiver-arguments.json` in the generated folder.
2. Copy the generated `server` folder to the storage server. Put its HTTPS
   certificate and private key at the paths you selected.
3. From that folder, run `python start_receiver.py`. Leave it running while
   testing. It listens on port 8766 by default; allow access from your meter on
   your local network if the server firewall requires it. Do not expose it to
   the Internet just to use this feature.

Docker is optional; running the Python receiver directly is supported.
For a server-hosted container, see the [NAS/container recipe](IMAGE-ARCHIVE-CONTAINER.md).
The generator does not install a background service or configure your NAS.
There is no image-browsing website at the receiver address.

## Test the connection without a meter image

With the receiver running, open a terminal in the repository's
`tools/image-archive` folder and run:

```sh
python probe_archive_receiver.py --host storage.example.net --ca-file /path/to/ca.pem --token-file /path/to/archive-setup/server/archive-token.txt
```

Use your receiver's actual hostname, CA certificate and generated token file.
Use `--port` if it is not on port 8766. This computer must be allowed through the
receiver's firewall. The probe creates a small, solid-color PNG locally, uploads
its synthetic metadata, and checks that uploading the same capture again is
recognized as a duplicate. It never connects to the meter or reads camera images.

Success means TLS, authentication and the receiver's hash receipts passed from
this computer. It does not prove that the ESP32 can reach the receiver. For an
independent disk check, run the archive audit described in the tools README.
The synthetic capture stays in the archive under device `synthetic-probe`,
unreviewed and ineligible for training. No files are deleted. Each invocation
creates a new synthetic capture identity. If a request fails, records might
already exist; the probe stops without automatically repeating an uncertain
write. Neither tokens nor server error bodies are printed.

## Enable it on a compatible AIEdge build

1. Open **Settings → Image archive** on a compatible AIEdge build.
2. Enter your receiver address, port and device name from the generated
   `meter-config/image-archive.json`.
3. Paste the contents of `image-archive-token.txt` into **Receiver access token**
   and `image-archive-ca.pem` into **Receiver CA certificate**. Never copy the
   server's private key to the meter.
4. Enable **Save camera images to the server**, then select **Save settings**.
   Restart the meter when ready to apply them. Saving does not restart it or
   redirect the running uploader.

On later edits, leave the token and certificate blank to retain saved values.
If a save is uncertain, reload settings before trying again; do not keep clicking
Save. Changes in another tab are rejected instead of silently overwritten.

For offline SD setup, preserve any existing settings, power off the meter and
copy the generated `image-archive-settings.json` into the card's `config` folder.
Reinsert it and restart. That file is authoritative on current builds. The three
legacy files are provided for older development builds; editing them has no
effect while the unified file exists.

Current archival requires the frozen PolarV1 reading profile and no separate
digital reader. Changing an active server, token or profile requires a controlled
restart. Previously queued images retain their original destination.

## Check that it works

Open `/image_archive_status` on the device. A queued image is not yet an uploaded
image: check upload acknowledgments and inspect files on the server. Stored
records include image hashes and remain unreviewed. Device timestamps distinguish
capture timing from retrieval; an unknown UTC capture time stays unknown.

Archiving is best effort. A slow server or storage device can cause counted
misses rather than holding up recognition. There is no automatic server-retention
policy: monitor free space and decide how long to keep captures. An upload error
must not be treated as successful storage.

To stop new submissions, clear **Save camera images to the server**, save and
restart. Already queued records may be completed before shutdown. Disabling
archival does not erase images already stored on either device.

For implementation details, see [archive status](../IMAGE-ARCHIVE-STATUS.md).


## Review the collected data

The [read-only archive check](../tools/image-archive/README.md#check-collected-images-before-review)
verifies saved image hashes and camera-settings records, lists failures, and
counts exact repeated images. Run it before choosing images to label. Different
lighting or calibration settings appear as separate groups for review; they are
not automatically combined into training data. A passing check proves file
integrity, not correct needle readings.
