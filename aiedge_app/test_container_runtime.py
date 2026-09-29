"""Run the packaged service itself, not only modules imported from the test mount."""
import json, os, pathlib, socket, subprocess, sys, tempfile, time, unittest, urllib.request

@unittest.skipUnless(os.environ.get('AIEDGE_CONTAINER_TEST')=='1','Linux container runtime only')
class ContainerRuntimeTests(unittest.TestCase):
    def test_packaged_service_startup_and_persistent_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            for attempt in range(2):
                with socket.socket() as probe:
                    probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
                command=[sys.executable,'/opt/aiedge/service.py','--data',directory,'--port',str(port),
                         '--native-library','/opt/aiedge/libaiedge_native.so','--models','/opt/aiedge/assets/models']
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
                    self.assertEqual(state['reading']['state'],'not_configured')
                    self.assertEqual(state['recognition']['state'],'not_configured')
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/setup') as r:setup=json.load(r)
                    self.assertTrue(setup['available']);self.assertIsNone(setup['calibration'])
                    for route,needle in [('/',b'Number format'),('/reading-format.js',b'openReadingFormat'),('/dashboard.js',b'visibilitychange'),('/favicon.svg',b'<svg')]:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}'+route) as r:self.assertIn(needle,r.read())
                    self.assertTrue((pathlib.Path(directory)/'captures.sqlite3').is_file())
                finally:
                    if process.poll() is None:process.terminate()
                    try:process.communicate(timeout=5)
                    except subprocess.TimeoutExpired:process.kill();process.communicate()

if __name__=='__main__':unittest.main()
