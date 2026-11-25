import json
import unittest
from contextlib import contextmanager
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from types import SimpleNamespace
from unittest.mock import patch

from camera_setup import check_camera_login
from capture import Camera
from http_server import AppHTTPServer
from service import handler


@contextmanager
def serving(server_type, request_handler):
    with server_type(('127.0.0.1', 0), request_handler) as server:
        thread = Thread(target=server.serve_forever, kwargs={'poll_interval': .01})
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()


class CameraPage(BaseHTTPRequestHandler):
    def do_GET(self):
        authenticated = self.headers.get('Authorization') == 'Basic ' + self.server.camera.basic
        self.server.requests.append((self.path, self.headers.get('Authorization') is not None))
        status = 200 if authenticated else self.server.anonymous
        self.send_response(status)
        if status == 302:
            self.send_header('Location', '/unexpected')
        body = self.server.message if status == 200 else b''
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class CameraLoginTest(unittest.TestCase):
    def setUp(self):
        self.server = self.enterContext(serving(HTTPServer, CameraPage))
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.server.camera = self.camera = Camera(self.url, username='admin', password='fixture')
        self.server.requests = []
        self.server.anonymous = 401
        self.server.message = b'Website password is already configured.'

    def test_operator_route_uses_running_collector(self):
        with patch('service.secrets.token_urlsafe', return_value='operator-test-token'):
            app = handler(None, False, SimpleNamespace(camera=self.camera), setup=object())
        with serving(AppHTTPServer, app) as api:
            def post(token, payload):
                conn = HTTPConnection('127.0.0.1', api.server_port, timeout=2)
                try:
                    conn.request('POST', '/api/camera-login-check', json.dumps(payload),
                                 {'X-AIEdge-Setup': token, 'Content-Type': 'application/json'})
                    response = conn.getresponse()
                    return response.status, response.read()
                finally:
                    conn.close()

            self.assertEqual(post('', {})[0], 403)
            self.assertEqual(post('operator-test-token', {'url': self.url})[0], 400)
            self.assertEqual(self.server.requests, [])
            status, body = post('operator-test-token', {})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), dict(endpoint='/auth/setup', unauthenticated=401,
                             configured_login=200, expected_body_matched=True, verified=True))
            self.assertEqual(self.server.requests, [('/auth/setup', False), ('/auth/setup', True)])

    def test_unprotected_and_redirected_pages_never_receive_credentials(self):
        for status in (200, 302, 403):
            with self.subTest(status=status):
                self.server.anonymous = status
                self.server.requests.clear()
                self.assertFalse(check_camera_login(self.camera)['verified'])
                self.assertEqual(self.server.requests, [('/auth/setup', False)])

    def test_wrong_or_missing_password(self):
        self.assertFalse(check_camera_login(Camera(self.url))['verified'])
        self.assertEqual(self.server.requests, [])
        wrong = Camera(self.url, username='admin', password='wrong')
        result = check_camera_login(wrong)
        self.assertFalse(result['verified'])
        self.assertEqual(result['configured_login'], 401)

    def test_response_must_be_the_exact_status_message(self):
        for body in (b'camera dashboard', self.server.message + b'more'):
            with self.subTest(body=body):
                self.server.message = body
                self.assertFalse(check_camera_login(self.camera)['verified'])

    def test_transport_error_returns_only_safe_status(self):
        with patch.object(self.camera.opener, 'open', side_effect=TimeoutError('private detail')):
            result = check_camera_login(self.camera)
        self.assertFalse(result['verified'])
        self.assertIsNone(result['configured_login'])
        self.assertNotIn('private detail', str(result))
