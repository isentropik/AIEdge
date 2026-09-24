"""Real loopback HTTP requests; no meter or remote storage access."""
import base64
import http.client
import json
import socket
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from image_archive_receiver import ArchiveServer
from image_archive_store import canonical, digest, store_settings


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.token = 'a' * 40
        self.server = ArchiveServer(('127.0.0.1', 0), self.root, self.token, timeout=1)
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.01})
        self.worker.start()
        self.addCleanup(self.cleanup)
        self.settings = b'capture-settings-v1\nsource=driver-status-and-capture-config\n'
        store_settings(self.root, digest(self.settings), self.settings)
        self.image = b'original bytes'
        self.metadata = dict(version=1, device_id='meter', boot_id='boot', capture_us=42,
            capture_utc=None, image_sha256=digest(self.image), image_bytes=len(self.image),
            firmware_sha256='1'*64, model_sha256='2'*64, calibration_sha256='3'*64, settings_sha256=digest(self.settings))

    def cleanup(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=3)
        self.tmp.cleanup()

    def post(self, changes=None, image=None, path='/v1/captures'):
        headers = {'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/octet-stream',
                   'X-Meter-Metadata': base64.b64encode(canonical(self.metadata)).decode()}
        headers.update(changes or {})
        conn = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        try:
            conn.request('POST', path, self.image if image is None else image, headers)
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()
            # Receipt arrival can precede worker teardown. Keep these sequential
            # parser/storage cases from accidentally exercising admission limits.
            acquired = 0
            try:
                for _ in range(4):
                    if not self.server.slots.acquire(timeout=3):
                        raise AssertionError('Receiver worker did not finish')
                    acquired += 1
            finally:
                for _ in range(acquired):
                    self.server.slots.release()

    def test_upload_retry_and_conflict(self):
        status, first = self.post()
        self.assertEqual(status, 201)
        status, retry = self.post()
        self.assertEqual(status, 200)
        self.assertEqual(first['capture_id'], retry['capture_id'])
        self.assertTrue(retry['duplicate'])
        self.assertFalse(retry['training_eligible'])
        self.metadata['model_sha256'] = '9'*64
        self.assertEqual(self.post()[0], 409)
        self.assertEqual(len(list(self.root.rglob('*.json'))), 1)

    def test_bad_requests_write_nothing(self):
        for headers, expected in [({'Authorization':'Bearer wrong'},401),
                                  ({'Content-Length':'99999999'},400),
                                  ({'X-Meter-Metadata':'bad'},400),
                                  ({'Content-Encoding':'gzip'},400),
                                  ({'Transfer-Encoding':'chunked'},400),
                                  ({'Content-Type':'text/plain'},400)]:
            with self.subTest(headers=headers):
                self.assertEqual(self.post(headers)[0], expected)
        self.assertEqual(self.post(path='/other')[0],404)
        self.assertEqual(self.post(image=b'changed bytes!')[0],400)
        self.assertFalse(list(self.root.rglob('*.image')))

    def test_storage_failure_has_no_success_receipt(self):
        with patch('image_archive_store.os.link', side_effect=OSError('disk fault')):
            status, result = self.post()
        self.assertEqual(status,503)
        self.assertNotIn('verified_readback',result)
        self.assertEqual(self.post()[0],201)

    def test_settings_required_and_retry(self):
        path = self.root/'settings'/f'{digest(self.settings)}.txt'
        path.unlink()
        self.assertEqual(self.post()[0], 409)
        self.assertFalse(list(self.root.rglob('*.image')))
        headers = {'X-Settings-SHA256': digest(self.settings)}
        status, receipt = self.post(headers, image=self.settings, path='/v1/settings')
        self.assertEqual(status, 201)
        self.assertTrue(receipt['verified_readback'])
        self.assertEqual(self.post(headers, image=self.settings, path='/v1/settings')[0], 200)
        self.assertEqual(self.post()[0], 201)
        path.write_bytes(b'corrupt')
        self.assertEqual(self.post()[0], 409)
        self.assertEqual(self.post(headers, image=self.settings, path='/v1/settings')[0], 409)

    def test_invalid_settings(self):
        for descriptor in [b'wrong\n', b'capture-settings-v1\n\x00', b'capture-settings-v1\n'+b'x'*8192]:
            self.assertEqual(self.post({'X-Settings-SHA256': digest(descriptor)}, image=descriptor, path='/v1/settings')[0], 400)
        self.assertEqual(self.post({'X-Settings-SHA256':'0'*64}, image=self.settings, path='/v1/settings')[0], 400)

    def test_duplicate_metadata_key(self):
        raw = canonical(self.metadata)
        raw = b'{"version":1,' + raw[1:]
        self.assertEqual(self.post({'X-Meter-Metadata':base64.b64encode(raw).decode()})[0],400)

    def test_incomplete_headers_expire_and_release_worker(self):
        with socket.create_connection(self.server.server_address, timeout=3) as conn:
            conn.sendall(b'POST /v1/captures HTTP/1.1\r\nX-Unfinished: ')
            # The total deadline closes even a partially sent header block.
            self.assertEqual(conn.recv(1024), b'')
        self.assertEqual(self.post()[0],201)

    def test_partial_body_disconnect_then_retry(self):
        metadata = base64.b64encode(canonical(self.metadata)).decode()
        headers = (f'POST /v1/captures HTTP/1.0\r\n'
                   f'Authorization: Bearer {self.token}\r\n'
                   f'Content-Type: application/octet-stream\r\n'
                   f'Content-Length: {len(self.image)}\r\n'
                   f'X-Meter-Metadata: {metadata}\r\n\r\n').encode()
        with socket.create_connection(self.server.server_address, timeout=3) as conn:
            conn.sendall(headers + self.image[:3])
            conn.shutdown(socket.SHUT_WR)
            response = b''
            while chunk := conn.recv(4096):
                response += chunk
        self.assertIn(b'400 Bad Request', response)
        self.assertNotIn(b'verified_readback', response)
        self.assertFalse(list(self.root.rglob('*.image')))
        self.assertFalse(list(self.root.rglob('*.json')))
        self.assertEqual(self.post()[0], 201)

    def test_commit_with_lost_receipt_then_retry(self):
        from image_archive_receiver import ArchiveHandler
        original = ArchiveHandler.reply
        dropped = []
        def disconnect(handler, status, payload):
            if status == 201:
                dropped.append(payload['capture_id'])
                handler.close_connection = True
                handler.connection.shutdown(socket.SHUT_RDWR)
                return
            return original(handler, status, payload)
        with patch.object(ArchiveHandler, 'reply', disconnect):
            with self.assertRaises(http.client.RemoteDisconnected):
                self.post()
        self.assertEqual(len(dropped), 1)
        status, receipt = self.post()
        self.assertEqual(status, 200)
        self.assertEqual(receipt['capture_id'], dropped[0])
        self.assertTrue(receipt['duplicate'])
        self.assertTrue(receipt['verified_readback'])
        self.assertFalse(receipt['training_eligible'])
        self.assertEqual(len(list((self.root/'captures').glob('*.json'))), 1)
        blobs = list((self.root/'blobs').glob('*.image'))
        self.assertEqual(len(blobs), 1)
        self.assertEqual(blobs[0].read_bytes(), self.image)

class DeadlineDisconnectTests(unittest.TestCase):
    def test_header_read_disconnect_is_contained(self):
        from image_archive_receiver import ArchiveHandler
        handler = object.__new__(ArchiveHandler)
        with patch('http.server.BaseHTTPRequestHandler.handle', side_effect=BrokenPipeError('deadline')):
            handler.handle()
        self.assertTrue(handler.close_connection)

    def test_programming_error_is_not_hidden(self):
        from image_archive_receiver import ArchiveHandler
        handler = object.__new__(ArchiveHandler)
        with patch('http.server.BaseHTTPRequestHandler.handle', side_effect=RuntimeError('bug')):
            with self.assertRaises(RuntimeError):
                handler.handle()


if __name__ == '__main__':
    unittest.main()
