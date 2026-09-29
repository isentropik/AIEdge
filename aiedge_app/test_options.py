"""Malformed configuration must remain diagnosable without outbound activity."""
from contextlib import closing
import json, socket, subprocess, sys, tempfile, time, unittest, urllib.request
from pathlib import Path
from unittest.mock import patch
from options import DEFAULTS, MAX_OPTIONS, load, validate, InvalidOptions
from capture import Camera


class OptionsTests(unittest.TestCase):
    def test_defaults_and_valid_disabled_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            options, status = load(directory)
            self.assertEqual(options, DEFAULTS)
            self.assertEqual(status, {'state': 'ready'})
            self.assertFalse((Path(directory)/'options.json').exists())
        value = validate({'camera_url':'https://camera.local:8443', 'camera_username':'admin',
                          'camera_password':'private', 'interval_seconds':60})
        self.assertFalse(value['capture_enabled'])
        self.assertEqual(value['interval_seconds'],60)

    def test_invalid_documents_never_enable_workers_or_expose_values(self):
        documents = [[], None, {'extra_secret':'DO-NOT-EXPOSE'}, {'capture_enabled':1},
                     {'mqtt_enabled':'true'}, {'interval_seconds':True}, {'interval_seconds':9},
                     {'interval_seconds':3601}, {'interval_seconds':30.0}, {'camera_password':[]},
                     {'camera_token':'x'*4097}, {'camera_token':'token with space'}, {'camera_token':'token\u2603'}, {'capture_enabled':True},
                     {'camera_url':'http://name:bad'}, {'camera_url':'http://name:70000'},
                     {'camera_url':'http://name:0'}, {'camera_url':'http://user:secret@name'},
                     {'camera_url':'http://name/path'}, {'camera_url':'http://name?secret=x'},
                     {'camera_url':'http://name\n'}, {'camera_username':'admin'},
                     {'camera_password':'DO-NOT-EXPOSE'}, {'camera_token':'token','camera_username':'user','camera_password':'pass'}]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'options.json'
            for document in documents:
                with self.subTest(document=document):
                    blob=json.dumps(document).encode();path.write_bytes(blob)
                    options,status=load(directory)
                    self.assertEqual(options,DEFAULTS)
                    self.assertEqual(status['state'],'invalid')
                    self.assertNotIn('DO-NOT-EXPOSE',json.dumps(status))
                    self.assertEqual(path.read_bytes(),blob)

    def test_invalid_encoding_size_nesting_duplicates_and_unreadable(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'options.json'
            for blob in (b'{broken', b'\xff', b'x'*(MAX_OPTIONS+1), b'['*2000+b']'*2000,
                         b'{"capture_enabled":false,"capture_enabled":true}'):
                path.write_bytes(blob)
                self.assertEqual(load(directory)[1]['state'],'invalid')
                self.assertEqual(path.read_bytes(),blob)
            with patch('options.Path.open',side_effect=PermissionError('SECRET')):
                options,status=load(directory)
            self.assertEqual(status,{'state':'invalid','code':'options_unreadable'})
            self.assertEqual(options,DEFAULTS)

    def test_corrected_options_apply_on_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'options.json';path.write_bytes(b'broken')
            self.assertEqual(load(directory)[1]['state'],'invalid')
            path.write_text(json.dumps({'capture_enabled':False,'interval_seconds':60}),encoding='utf-8')
            options,status=load(directory)
            self.assertEqual(status,{'state':'ready'})
            self.assertEqual(options['interval_seconds'],60)


class OptionsProcessTests(unittest.TestCase):
    def test_invalid_options_keep_http_available_and_do_not_call_camera(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        requests=[]
        class CameraHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(self.path);self.send_response(500);self.end_headers()
            def log_message(self,*args):pass
        camera=ThreadingHTTPServer(('127.0.0.1',0),CameraHandler)
        thread=threading.Thread(target=camera.serve_forever,daemon=True);thread.start()
        try:
            cases=[b'BROKEN-SECRET',json.dumps({'camera_url':f'http://127.0.0.1:{camera.server_port}',
                   'capture_enabled':True,'mqtt_enabled':True,'interval_seconds':False}).encode(),
                   json.dumps({'mqtt_enabled':True}).encode()]
            for blob in cases:
                with self.subTest(blob=blob),tempfile.TemporaryDirectory() as directory:
                    path=Path(directory)/'options.json';path.write_bytes(blob)
                    with socket.socket() as probe:
                        probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
                    process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('service.py')),
                         '--data',directory,'--port',str(port)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                    try:
                        deadline=time.monotonic()+15
                        while True:
                            if process.poll() is not None:self.fail('Service exited unexpectedly')
                            try:
                                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status',timeout=1) as response:
                                    status=json.load(response)
                                break
                            except OSError:
                                if time.monotonic()>deadline:raise
                                time.sleep(.05)
                        self.assertEqual(status['configuration']['state'],'invalid')
                        self.assertFalse(status['capture_enabled'])
                        self.assertEqual(status['mqtt']['state'],'disabled')
                        self.assertEqual(requests,[])
                        self.assertNotIn('SECRET',json.dumps(status))
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/') as response:
                            self.assertIn(b'AIEdge',response.read())
                        self.assertEqual(path.read_bytes(),blob)
                    finally:
                        process.terminate()
                        try:process.communicate(timeout=5)
                        except subprocess.TimeoutExpired:process.kill();process.communicate()
        finally:
            camera.shutdown();camera.server_close();thread.join()

class StorageStartupTests(unittest.TestCase):
    def test_damaged_database_preserves_file_and_serves_shell(self):
        import sqlite3
        for wrong_schema in (False, True):
            with self.subTest(wrong_schema=wrong_schema), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);path=root/'captures.sqlite3'
                if wrong_schema:
                    with closing(sqlite3.connect(path)) as db:
                        db.execute('CREATE TABLE frames(wrong_column TEXT)');db.commit()
                else:path.write_bytes(b'NOT-A-DATABASE-PRESERVE-ME')
                before=path.read_bytes()
                (root/'options.json').write_text(json.dumps({'capture_enabled':True,'camera_url':'http://127.0.0.1:1','mqtt_enabled':True}),encoding='utf-8')
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
                process=subprocess.Popen([sys.executable,str(Path(__file__).with_name('service.py')),
                    '--data',directory,'--port',str(port)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                try:
                    deadline=time.monotonic()+15
                    while True:
                        if process.poll() is not None:self.fail('Storage failure stopped HTTP startup')
                        try:
                            with urllib.request.urlopen(f'http://127.0.0.1:{port}/',timeout=1) as response:
                                self.assertIn(b'AIEdge',response.read())
                            break
                        except OSError:
                            if time.monotonic()>deadline:raise
                            time.sleep(.05)
                    for endpoint in ('api/status','api/captures','api/setup','api/reading-format'):
                        with self.assertRaises(urllib.error.HTTPError) as raised:
                            urllib.request.urlopen(f'http://127.0.0.1:{port}/'+endpoint,timeout=2)
                        with raised.exception as response:
                            self.assertEqual(response.code,503)
                            self.assertEqual(json.load(response)['code'],'storage_startup_failed')
                    self.assertEqual(path.read_bytes(),before)
                    self.assertFalse((root/'instance-id').exists())
                    if wrong_schema:
                        with closing(sqlite3.connect(path)) as db:
                            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(),[('frames',)])
                finally:
                    process.terminate()
                    try:process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:process.kill();process.communicate()

if __name__=='__main__':unittest.main()
