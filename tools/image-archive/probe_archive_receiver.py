"""Send one synthetic image to an HTTPS archive receiver; never contact a meter."""
import argparse
import base64
import http.client
import json
from pathlib import Path
import re
import ssl
import struct
import uuid
import zlib

from image_archive_store import canonical, digest


class ProbeError(Exception):
    pass


def synthetic_png():
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!IIBBBBB', 16, 16, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress((b'\0' + b'\x30\x80\xc0' * 16) * 16)) + chunk(b'IEND', b''))


def post(host, port, context, token, path, body, headers, timeout):
    # Direct connection: no environment proxies, redirects, or automatic retry.
    connection = http.client.HTTPSConnection(host, port, context=context, timeout=timeout)
    try:
        connection.request('POST', path, body, {'Authorization': 'Bearer ' + token,
                           'Content-Type': 'application/octet-stream', **headers})
        response = connection.getresponse()
        if response.status not in (200, 201):
            raise ProbeError('HTTP ' + str(response.status))
        raw = response.read(8193)
        if len(raw) > 8192:
            raise ProbeError('Receipt exceeds 8192 bytes')
        try:
            receipt = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ProbeError('Invalid JSON receipt') from None
        if not isinstance(receipt, dict):
            raise ProbeError('Receipt is not an object')
        return response.status, receipt
    finally:
        connection.close()


def run_probe(host, port, ca_file, token_file, timeout=15):
    if not host or any(c in host for c in '/\\@?#') or not 1 <= port <= 65535:
        raise ValueError('Use a host name or IP and a valid separate port')
    if not 0 < timeout <= 60:
        raise ValueError('Timeout must be greater than zero and at most 60 seconds')
    token = Path(token_file).read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', token):
        raise ValueError('Invalid token file')
    context = ssl.create_default_context(cafile=str(ca_file))
    identity = uuid.uuid4().hex
    settings = ('capture-settings-v1\nsource=synthetic-connection-probe\nprobe=' + identity + '\n').encode('ascii')
    image = synthetic_png()
    marker = digest(b'synthetic connection probe; not a firmware, model, or calibration')
    metadata = dict(version=1, device_id='synthetic-probe', boot_id=identity, capture_us=0,
                    capture_utc=None, image_sha256=digest(image), image_bytes=len(image),
                    firmware_sha256=marker, model_sha256=marker, calibration_sha256=marker,
                    settings_sha256=digest(settings))
    capture_id = digest(canonical({key: metadata[key] for key in ('device_id', 'boot_id', 'capture_us')}))
    record = dict(capture_id=capture_id, metadata=metadata, review_status='unreviewed', training_eligible=False)
    expected = dict(version=1, capture_id=capture_id, image_sha256=digest(image),
                    record_sha256=digest(canonical(record)), verified_readback=True,
                    review_status='unreviewed', training_eligible=False)
    stage = 'settings upload'
    try:
        status, receipt = post(host, port, context, token, '/v1/settings', settings,
                               {'X-Settings-SHA256': digest(settings)}, timeout)
        if status != 201 or canonical(receipt) != canonical(dict(version=1, settings_sha256=digest(settings), verified_readback=True, duplicate=False)):
            raise ProbeError('Unexpected settings receipt')
        headers = {'X-Meter-Metadata': base64.b64encode(canonical(metadata)).decode('ascii')}
        for duplicate in (False, True):
            stage = 'duplicate upload' if duplicate else 'image upload'
            status, receipt = post(host, port, context, token, '/v1/captures', image, headers, timeout)
            # JSON encoding distinguishes true from 1 and false from 0.
            if status != (200 if duplicate else 201) or canonical(receipt) != canonical(dict(expected, duplicate=duplicate)):
                raise ProbeError('Unexpected image receipt')
    except Exception as error:
        detail = str(error) if isinstance(error, ProbeError) else type(error).__name__
        raise ProbeError(stage + ': ' + detail + '. Records may have been saved; no automatic retry performed.') from None
    return dict(success=True, synthetic=True, capture_id=capture_id, image_sha256=digest(image),
                duplicate_verified=True, training_eligible=False,
                limitation='Checks receiver receipts from this computer, not ESP32 delivery or independent filesystem readback.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--ca-file', type=Path, required=True)
    parser.add_argument('--token-file', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=15)
    args = parser.parse_args()
    try:
        result = run_probe(**vars(args))
    except Exception as error:
        print(json.dumps({'success': False, 'error': str(error) if isinstance(error, (ProbeError, ValueError)) else type(error).__name__}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
