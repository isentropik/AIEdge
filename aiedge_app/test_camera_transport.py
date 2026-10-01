"""Real loopback HTTP/TLS checks for deadline, buffering and trust boundaries."""
import contextlib,errno,socket,ssl,threading,time,unittest,urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from capture import Camera,NoRedirect
from camera_transport import DeadlineHTTPHandler,DeadlineHTTPSHandler
import camera_transport
from test_capture import JPEG,headers

CERT=Path(__file__).parent/'test-fixtures/transport-test-cert.pem'
KEY=Path(__file__).parent/'test-fixtures/transport-test-key.pem'

@contextlib.contextmanager
def fixture(mode='ok',tls=False):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            status=503 if mode=='error_body' else 200
            blob=b'Unexpected private details'*5 if mode=='error_body' else JPEG
            fields={'Content-Type':'text/plain' if status==503 else 'image/jpeg','Content-Length':str(len(blob)),**dict(headers().items())}
            wire=(f'HTTP/1.0 {status} Result\r\n'+''.join(f'{name}: {value}\r\n' for name,value in fields.items())).encode()
            try:
                if mode=='headers':
                    self.connection.sendall(b'HTTP/1.0 200 OK\r\nX-Slow: ')
                    for _ in range(50):self.connection.sendall(b'a');time.sleep(.04)
                    self.connection.sendall(b'\r\nContent-Length: 5\r\n\r\n'+JPEG)
                elif mode=='delayed_body':
                    self.connection.sendall(wire+b'\r\n')
                    time.sleep(5.2)
                    self.connection.sendall(blob)
                elif mode in ('body','error_body'):
                    self.connection.sendall(wire+b'\r\n')
                    for byte in blob:self.connection.sendall(bytes([byte]));time.sleep(.06)
                else:self.connection.sendall(wire+b'\r\n'+blob)
            except (ConnectionError,OSError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    if tls:
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(CERT,KEY)
        server.socket=context.wrap_socket(server.socket,server_side=True)
    thread=threading.Thread(target=server.serve_forever);thread.start()
    try:yield ('https' if tls else 'http')+f'://127.0.0.1:{server.server_port}'
    finally:server.shutdown();thread.join(2);server.server_close()

class TransportTests(unittest.TestCase):
    def connection_fixture(self,platform='linux',option_error=None,connect_error=None):
        events=[]
        class Socket:
            def settimeout(self,value):events.append(('timeout',value))
            def setsockopt(self,*args):
                events.append(('option',args))
                if option_error:raise option_error
            def bind(self,value):events.append(('bind',value))
            def connect(self,value):
                events.append(('connect',value))
                if connect_error:raise connect_error
            def close(self):events.append(('close',))
        instance=Socket()
        patches=(patch.object(camera_transport.sys,'platform',platform),
                 patch.object(camera_transport.socket,'getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('10.1.0.127',80))]),
                 patch.object(camera_transport.socket,'socket',return_value=instance),
                 patch.object(camera_transport.time,'monotonic',return_value=10))
        return events,instance,patches

    def test_linux_negotiates_smaller_segments_before_connecting(self):
        events,instance,patches=self.connection_fixture()
        with contextlib.ExitStack() as stack:
            for p in patches:stack.enter_context(p)
            result=camera_transport.camera_connection(('meter',80),5,('10.1.1.43',0),deadline=30)
        self.assertIs(result,instance)
        self.assertEqual(events,[('timeout',5),('option',(socket.IPPROTO_TCP,socket.TCP_MAXSEG,512)),
                                 ('bind',('10.1.1.43',0)),('connect',('10.1.0.127',80))])

    def test_other_platforms_retain_the_standard_socket_path(self):
        events,_,patches=self.connection_fixture(platform='win32')
        with contextlib.ExitStack() as stack:
            for p in patches:stack.enter_context(p)
            camera_transport.camera_connection(('meter',80),5,deadline=30)
        self.assertEqual(events,[('timeout',5),('connect',('10.1.0.127',80))])

    def test_unsupported_segment_option_keeps_normal_connectivity(self):
        events,_,patches=self.connection_fixture(option_error=OSError(errno.ENOPROTOOPT,'unsupported'))
        with contextlib.ExitStack() as stack:
            for p in patches:stack.enter_context(p)
            camera_transport.camera_connection(('meter',80),5,deadline=30)
        self.assertEqual(events[-1],('connect',('10.1.0.127',80)))

    def test_unexpected_socket_option_error_is_not_hidden(self):
        events,_,patches=self.connection_fixture(option_error=OSError(errno.EPERM,'denied'))
        with contextlib.ExitStack() as stack:
            for p in patches:stack.enter_context(p)
            with self.assertRaises(OSError):camera_transport.camera_connection(('meter',80),5,deadline=30)
        self.assertEqual(events[-1],('close',))
        self.assertFalse(any(row[0]=='connect' for row in events))

    def test_failed_connection_closes_its_socket(self):
        events,_,patches=self.connection_fixture(connect_error=ConnectionRefusedError('fixture'))
        with contextlib.ExitStack() as stack:
            for p in patches:stack.enter_context(p)
            with self.assertRaises(ConnectionRefusedError):camera_transport.camera_connection(('meter',80),5,deadline=30)
        self.assertEqual(events[-1],('close',))

    def test_connection_setup_uses_only_the_remaining_deadline(self):
        events,_,patches=self.connection_fixture()
        with contextlib.ExitStack() as stack:
            for p in patches:stack.enter_context(p)
            camera_transport.camera_connection(('meter',80),5,deadline=11)
        self.assertEqual(events[0],('timeout',1))

    def test_expired_deadline_never_opens_a_socket(self):
        events,_,patches=self.connection_fixture()
        with contextlib.ExitStack() as stack:
            for p in patches:stack.enter_context(p)
            with self.assertRaises(TimeoutError):camera_transport.camera_connection(('meter',80),5,deadline=10)
        self.assertEqual(events,[])

    def test_ipv6_destination_is_preserved(self):
        events,_,patches=self.connection_fixture()
        destination=('fd00::127',80,0,0)
        with contextlib.ExitStack() as stack:
            for p in patches:stack.enter_context(p)
            with patch.object(camera_transport.socket,'getaddrinfo',return_value=[(socket.AF_INET6,socket.SOCK_STREAM,6,'',destination)]):
                camera_transport.camera_connection(('meter',80),5,deadline=30)
        self.assertEqual(events[-1],('connect',destination))

    def test_address_fallback_does_not_restart_the_connect_budget(self):
        events,first,patches=self.connection_fixture(connect_error=ConnectionRefusedError('first address'))
        second_events,second,_=self.connection_fixture()
        addresses=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('10.1.0.126',80)),
                   (socket.AF_INET,socket.SOCK_STREAM,6,'',('10.1.0.127',80))]
        with contextlib.ExitStack() as stack:
            for p in patches:stack.enter_context(p)
            with patch.object(camera_transport.socket,'getaddrinfo',return_value=addresses), \
                 patch.object(camera_transport.socket,'socket',side_effect=[first,second]), \
                 patch.object(camera_transport.time,'monotonic',side_effect=[10,14]):
                result=camera_transport.camera_connection(('meter',80),5,deadline=15)
        self.assertIs(result,second)
        self.assertEqual(events[-1],('close',))
        self.assertEqual(second_events[0],('timeout',1))

    def test_plain_and_tls_connections_use_the_same_socket_admission(self):
        for kind in (camera_transport.DeadlineConnection,camera_transport.DeadlineTLSConnection):
            connection=kind('meter',deadline=123)
            self.assertIs(connection._create_connection.func,camera_transport.camera_connection)
            self.assertEqual(connection._create_connection.keywords,{'deadline':123})

    def test_body_pause_over_five_seconds_still_within_total_deadline(self):
        with fixture('delayed_body') as url:
            start=time.monotonic();blob,metadata=Camera(url).capture()
            self.assertEqual(blob,JPEG)
            self.assertGreater(time.monotonic()-start,5)
            self.assertLess(time.monotonic()-start,8)

    def slow_failure(self,mode,tls=False,reason='camera_timeout'):
        with fixture(mode,tls) as url:
            camera=Camera(url)
            if tls:self.trust_fixture(camera)
            start=time.monotonic()
            with patch('capture.CAPTURE_IO_DEADLINE',.2),self.assertRaisesRegex(ValueError,'^'+reason+'$'):camera.capture()
            self.assertLess(time.monotonic()-start,.8)
    def trust_fixture(self,camera):
        context=ssl.create_default_context(cafile=str(CERT))
        self.assertTrue(context.check_hostname);self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
        camera.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),DeadlineHTTPHandler(),DeadlineHTTPSHandler(context=context))
    def test_trickled_header_obeys_the_overall_io_deadline(self):self.slow_failure('headers')
    def test_trickled_body_obeys_the_same_deadline(self):self.slow_failure('body')
    def test_trickled_error_body_is_bounded_and_never_exposed(self):self.slow_failure('error_body',reason='camera_unavailable')
    def test_tls_headers_obey_the_same_deadline(self):self.slow_failure('headers',tls=True)
    def test_default_tls_rejects_the_disposable_untrusted_certificate(self):
        with fixture(tls=True) as url:
            with self.assertRaisesRegex(ValueError,'^camera_certificate_invalid$'):Camera(url).capture()
    def test_trusted_tls_preserves_complete_image_and_capture_metadata(self):
        with fixture(tls=True) as url:
            camera=Camera(url);self.trust_fixture(camera);blob,metadata=camera.capture()
            self.assertEqual(blob,JPEG)
            for name,value in headers().items():self.assertEqual(metadata[name],value)
    def test_buffered_http_headers_do_not_consume_image_bytes(self):
        with fixture() as url:
            blob,metadata=Camera(url).capture();self.assertEqual(blob,JPEG)
            self.assertEqual(metadata['Content-Length'],str(len(JPEG)))

if __name__=='__main__':unittest.main()
