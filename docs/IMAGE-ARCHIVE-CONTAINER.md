# Run the image receiver on a NAS or Linux server

This optional container runs the same HTTPS receiver as the Python setup. It lets
your storage server receive images without leaving a separate computer running.
It does not install anything on the ESP32 or change your existing archive.

**Development recipe:** container build and NAS execution have not yet been
verified. Docker is unavailable in the current development environment. The
receiver itself has separate Python/TLS tests; those do not verify Docker mounts,
NAS permissions, or delivery from your meter. There is no published container image.

## Prepare storage and HTTPS

First follow [Prepare the files](IMAGE-ARCHIVE.md#prepare-the-files) to generate
matching meter and receiver settings. Keep the generated token private. You also
need the server certificate and private key described in that guide.

Use an existing folder on the server. For a share such as
`\\nas\meter-images`, find its local filesystem path in your NAS settings;
do not put the Windows network path into a Linux container mount. This container
writes locally on the NAS, so it does not need an SMB username or password.

Choose a non-root server user/group that can write the archive and read the token,
certificate and private key. Preserve existing folder permissions; do not make
private keys world-readable or recursively change ownership of an existing share.
The receiver uses hard links on Linux to avoid overwriting existing captures.
Use the storage probe described in the [tool guide](../tools/image-archive/README.md)
to check the intended filesystem before enabling uploads.

## Configure the container

Copy this repository to the server and open `tools/image-archive`. Create a private
file named `.env` beside `compose.yaml` using these keys. Replace every example;
the IDs below are examples, not assumed NAS account IDs:

```dotenv
ARCHIVE_UID=1000
ARCHIVE_GID=1000
ARCHIVE_BIND_IP=192.168.1.20
ARCHIVE_FOLDER=/srv/aiedge/images
ARCHIVE_TOKEN_FILE=/srv/aiedge/setup/server/archive-token.txt
ARCHIVE_CERT_FILE=/srv/aiedge/tls/server.pem
ARCHIVE_KEY_FILE=/srv/aiedge/tls/server-key.pem
```

All paths belong to the Docker server. Keep `.env`, keys and generated settings
out of Git. Only paths and IDs belong in `.env`; the token stays in its generated
file. The selected account must be able to traverse each parent directory.

Review the resolved configuration before starting anything:

```sh
docker compose config
docker compose build
docker compose up -d
docker compose logs --tail 50
```

The build downloads the Python base image; it contains only the receiver and
storage code, not your token, images or keys. The Python base tag can change; record
the built image ID when testing. `docker compose images` shows the local image.

The service listens on the specified LAN IP at port 8766. The archive is writable;
the token and TLS files are read-only. Missing mount sources cause an error instead
of silently creating directories. No Docker socket, privileged mode or host-network
access is needed. Configure your server firewall to allow the meter; do not expose
this port to the Internet. Consult Docker's [bind-mount guide](https://docs.docker.com/engine/storage/bind-mounts/)
and [Compose service reference](https://docs.docker.com/reference/compose-file/services/)
for mount and networking behavior.

## Connect and verify

Use the same host/IP, port 8766, token and trusted CA in the meter's Image archive
settings. The HTTPS certificate must match that host/IP. The storage folder is a
server setting; the ESP32 does not see `/archive` or mount an SMB share.

A running container is not proof of a saved image. Check upload acknowledgments on
the meter and verify new server records with `audit_image_archive.py`. A TLS failure,
permission error, full disk or conflicting capture must remain a failure. Unknown
capture times and unreviewed labels stay unknown; nothing is admitted to training.
There is no image-browsing website at the receiver URL.

Stop the receiver with `docker compose down`. The bind-mounted archive remains on
the server. This stops delivery but does not disable the meter's upload queue;
disable archiving through the meter settings if that is your intent. To update,
review changes, rebuild the image and recreate the container. Keep credentials and
stored images unchanged unless you deliberately rotate or move them.
