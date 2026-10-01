"""Run the packaged service itself, not only modules imported from the test mount."""
import json, os, pathlib, socket, subprocess, sys, tempfile, time, unittest, urllib.request

@unittest.skipUnless(os.environ.get('AIEDGE_CONTAINER_TEST')=='1','Linux container runtime only')
class ContainerRuntimeTests(unittest.TestCase):
    def test_packaged_service_startup_and_persistent_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            for attempt in range(3):
                if attempt==2:
                    (pathlib.Path(directory)/'calibration.json').write_bytes(b'{broken calibration')
                    (pathlib.Path(directory)/'reading-format.json').write_bytes(b'{broken format')
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
                command=[sys.executable,'/opt/aiedge/service.py','--data',directory,'--port',str(port),
                         '--native-library','/opt/aiedge/libaiedge_native.so','--accounting-library','/opt/aiedge/libaiedge_accounting.so','--models','/opt/aiedge/assets/models']
                process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    deadline=time.monotonic()+20
                    while True:
                        if process.poll() is not None:
                            out,err=process.communicate();self.fail('Packaged service exited: '+out+err)
                        try:
                            with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status',timeout=1) as r:state=json.load(r)
                            break
                        except OSError:
                            if time.monotonic()>deadline:raise
                            time.sleep(.1)
                    self.assertFalse(state['capture_enabled']);self.assertEqual(state['captures'],0)
                    self.assertEqual(state['reading']['state'],'unavailable' if attempt==2 else 'not_configured')
                    if attempt==2:
                        self.assertEqual(state['setup_recovery']['code'],'saved_calibration_invalid')
                        self.assertEqual(state['format_recovery']['code'],'saved_reading_format_invalid')
                        self.assertEqual((pathlib.Path(directory)/'calibration.json').read_bytes(),b'{broken calibration')
                        self.assertEqual((pathlib.Path(directory)/'reading-format.json').read_bytes(),b'{broken format')
                    self.assertEqual(state['recognition']['state'],'not_configured')
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/setup') as r:setup=json.load(r)
                    self.assertTrue(setup['available']);self.assertIsNone(setup['calibration'])
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/camera-setup') as r:camera=json.load(r)
                    self.assertFalse(camera['configured']);self.assertFalse(camera['capture_enabled']);self.assertEqual(camera['state'],'idle')
                    for route,needle in [('/',b'Number format'),('/reading-format.js',b'openReadingFormat'),('/dashboard.js',b'visibilitychange'),('/favicon.svg',b'<svg'),('/editor-geometry.js',b'AIEdgeGeometry'),('/reference-image.js',b'AIEdgeReferenceImage'),('/setup-flow.js',b'AIEdgeFlow'),('/parity.css',b'setup-steps')]:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}'+route) as r:self.assertIn(needle,r.read())
                    self.assertTrue((pathlib.Path(directory)/'captures.sqlite3').is_file())
                    process.terminate()  # Actual Linux SIGTERM to the packaged service.
                    out,err=process.communicate(timeout=5)
                    self.assertEqual(process.returncode,0,out+err)
                    events=[json.loads(line) for line in out.splitlines() if line.startswith('{')]
                    stopped=[event for event in events if event.get('event')=='aiedge_stopped']
                    self.assertTrue(stopped,out+err)
                    self.assertTrue(stopped[-1]['requests_drained'])
                    self.assertEqual(stopped[-1]['pending_workers'],0)
                finally:
                    if process.poll() is None:process.terminate()
                    try:process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:process.kill();process.communicate()

if __name__=='__main__':unittest.main()
