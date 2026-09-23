"""Bounded archive receiver; run on the storage server against a local folder.

No device discovery or captures. Non-loopback listeners require TLS. An HTTPS
reverse proxy may instead forward to the default loopback listener.
"""
import argparse
import base64
import binascii
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import socket
import ssl
import threading
import time

from image_archive_store import ArchiveConflict, MAX_IMAGE_BYTES, canonical, store_capture, validate_metadata, store_settings, require_settings, MAX_SETTINGS_BYTES


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate metadata key')
        result[key] = value
    return result


class ArchiveServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = True

    def __init__(self, address, root, token, timeout=15, workers=4):
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', token):
            raise ValueError('Use a random URL-safe token of 32 to 256 characters')
        self.root = Path(root)
        if not self.root.is_absolute():
            raise ValueError('Archive folder must be absolute')
        if not 0 < timeout <= 60 or not 1 <= workers <= 16:
            raise ValueError('Invalid receiver limits')
        self.token = ('Bearer ' + token).encode('ascii')
        self.request_timeout = timeout
        self.slots = threading.BoundedSemaphore(workers)
        self.tls_context = None
        super().__init__(address, ArchiveHandler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            # Reject before creating another worker or buffering another image.
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        def expire():
            try:
                request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        deadline = threading.Timer(self.request_timeout, expire)
        deadline.daemon = True
        deadline.start()
        try:
            if self.tls_context is not None:
                request.settimeout(self.request_timeout)
                try:
                    request = self.tls_context.wrap_socket(request, server_side=True)
                except (OSError, ssl.SSLError):
                    request.close()
                    return
            super().process_request_thread(request, client_address)
        finally:
            deadline.cancel()
            self.slots.release()


class ArchiveHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'
    server_version = 'MeterArchive/1'

    def setup(self):
        super().setup()
        self.deadline = time.monotonic() + self.server.request_timeout
        self.connection.settimeout(self.server.request_timeout)

    def handle(self):
        try:
            super().handle()
        except OSError:
            # The absolute request deadline can close a socket while the HTTP
            # parser is still reading headers. Treat that as a disconnected
            # client, not a receiver crash or an uncaught worker traceback.
            self.close_connection = True

    def log_message(self, *_):
        # Never log request paths, authorization or metadata supplied by clients.
        pass

    def reply(self, status, payload):
        body = canonical(payload)
        self.close_connection = True
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(body)
            if status >= 400:
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_WR)
                # Do not close with a small rejected upload still in flight: TCP
                # may reset and discard the rejection. Bound both time and bytes.
                stop = min(self.deadline, time.monotonic() + 0.05)
                drained = 0
                while drained < 4096:
                    remaining = stop - time.monotonic()
                    if remaining <= 0:
                        break
                    self.connection.settimeout(remaining)
                    chunk = self.rfile.read1(4096 - drained)
                    if not chunk:
                        break
                    drained += len(chunk)
        except OSError:
            # Disconnected caller retries the immutable capture identity.
            pass

    def one_header(self, name):
        values = self.headers.get_all(name, [])
        if len(values) != 1:
            raise ValueError('Missing or repeated header')
        return values[0]

    def do_POST(self):
        try:
            auth = self.one_header('Authorization').encode('ascii')
            if not hmac.compare_digest(auth, self.server.token):
                self.reply(401, {'error': 'unauthorized'})
                return
            if self.path not in ('/v1/captures', '/v1/settings'):
                self.reply(404, {'error': 'not_found'})
                return
            if self.headers.get_all('Transfer-Encoding') or self.headers.get_all('Content-Encoding'):
                raise ValueError('Encoded body not supported')
            if self.one_header('Content-Type') != 'application/octet-stream':
                raise ValueError('Invalid content type')
            length = self.one_header('Content-Length')
            if not re.fullmatch(r'[0-9]{1,8}', length) or not 0 < int(length) <= MAX_IMAGE_BYTES:
                raise ValueError('Invalid length')
            if self.path == '/v1/settings':
                if int(length) > MAX_SETTINGS_BYTES:
                    raise ValueError('Settings too large')
                settings_hash = self.one_header('X-Settings-SHA256')
                if not re.fullmatch('[0-9a-f]{64}', settings_hash):
                    raise ValueError('Invalid settings hash')
            else:
                encoded = self.one_header('X-Meter-Metadata')
                if len(encoded) > 4096:
                    raise ValueError('Metadata too large')
                metadata = validate_metadata(json.loads(base64.b64decode(encoded, validate=True),
                                                         object_pairs_hook=unique_object))
                if metadata['image_bytes'] != int(length):
                    raise ValueError('Length mismatch')
                require_settings(self.server.root, metadata['settings_sha256'])
            image = bytearray()
            while len(image) < int(length):
                remaining = self.deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                self.connection.settimeout(remaining)
                chunk = self.rfile.read1(min(65536, int(length) - len(image)))
                if not chunk:
                    raise ValueError('Truncated body')
                image.extend(chunk)
            if self.path == '/v1/settings':
                receipt = store_settings(self.server.root, settings_hash, bytes(image))
            else:
                # Revalidate immediately before publishing the capture record.
                require_settings(self.server.root, metadata['settings_sha256'])
                receipt = store_capture(self.server.root, metadata, bytes(image))
            self.reply(200 if receipt['duplicate'] else 201, receipt)
        except ArchiveConflict:
            self.reply(409, {'error': 'archive_conflict'})
        except (ValueError, UnicodeError, binascii.Error):
            self.reply(400, {'error': 'invalid_request'})
        except (TimeoutError, socket.timeout):
            self.reply(408, {'error': 'upload_timeout'})
        except OSError:
            self.reply(503, {'error': 'storage_or_transport_unavailable'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--token-file', type=Path, required=True)
    parser.add_argument('--certificate', type=Path)
    parser.add_argument('--private-key', type=Path)
    args = parser.parse_args()
    if bool(args.certificate) != bool(args.private_key):
        parser.error('Both certificate and private key are required for TLS')
    if args.bind != '127.0.0.1' and not args.certificate:
        parser.error('Non-loopback listener requires TLS')
    token = args.token_file.read_text(encoding='ascii').strip()
    server = ArchiveServer((args.bind, args.port), args.folder, token)
    if args.certificate:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(args.certificate, args.private_key)
        # Handshake inside bounded workers, never in the accepting thread.
        server.tls_context = context
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
