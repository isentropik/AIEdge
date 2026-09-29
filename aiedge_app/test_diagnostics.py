import json,tempfile,threading,unittest,urllib.request
from pathlib import Path
from types import SimpleNamespace
from http.server import ThreadingHTTPServer
from diagnostics import build
from capture import Store
from service import handler

class DiagnosticsTests(unittest.TestCase):
    def test_report_excludes_credentials_readings_and_identifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            (Path(directory)/'options.json').write_text(json.dumps({'camera_password':'PRIVATE-PASSWORD','camera_url':'http://PRIVATE-CAMERA'}),encoding='utf-8')
            collector=SimpleNamespace(interval=30,missed_slots=1,last_error={'error':'PRIVATE-ERROR'},camera=SimpleNamespace(origin='PRIVATE-CAMERA'))
            reader=SimpleNamespace(dials=[{'name':'PRIVATE-NAME'}],pipeline_id='a'*64)
            recognition=SimpleNamespace(lock=threading.Lock(),reader=reader,last_error='PRIVATE-INFERENCE')
            setup=SimpleNamespace(status=lambda:{'calibration':{'private':'PRIVATE-GEOMETRY'},'recovery':{'detail':'PRIVATE-ERROR'}})
            mqtt=SimpleNamespace(status=lambda:{'state':'error','error':'PRIVATE-BROKER'})
            report=build(store,collector,recognition,setup,mqtt_output=mqtt)
            text=json.dumps(report)
            self.assertNotIn('PRIVATE-',text);self.assertNotIn(directory,text)
            self.assertEqual(report['capture']['captures'],0)
            self.assertTrue(report['capture']['current_failure'])
            self.assertTrue(report['calibration']['recovery_required'])
    def test_download_works_even_when_storage_cannot_open(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(None,False,None))
        thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/api/diagnostics') as response:
                self.assertIn('attachment',response.headers['Content-Disposition']);report=json.load(response)
            self.assertEqual(report['storage']['state'],'unavailable')
            self.assertFalse(report['capture']['enabled'])
            self.assertEqual(report['schema_version'],1)
        finally:server.shutdown();thread.join();server.server_close()

if __name__=='__main__':unittest.main()
