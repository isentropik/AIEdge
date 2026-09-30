import json,threading,unittest,urllib.request,urllib.error,http.client
from http.server import ThreadingHTTPServer
import test_setup
from test_setup import DESIGN,reference
from service import handler

class Tests(unittest.TestCase):
    setUp=test_setup.Tests.setUp
    tearDown=test_setup.Tests.tearDown
    def test_historical_failure_does_not_look_like_current_failure(self):
        from types import SimpleNamespace
        self.store.fail('earlier_capture_failed')
        collector=SimpleNamespace(last_error=None,missed_slots=0,interval=30)
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.store,False,collector))
        thread=threading.Thread(target=server.serve_forever);thread.start()
        origin='http://127.0.0.1:'+str(server.server_port)
        try:
            with urllib.request.urlopen(origin+'/api/status') as response:state=json.load(response)
            self.assertIsNone(state['last_error']);self.assertEqual(state['failures'],1)
            self.assertEqual(state['last_failure']['error'],'earlier_capture_failed')
            self.assertEqual(state['interval_seconds'],30)
            collector.last_error={'error':'current_failure','at':'fixture'}
            with urllib.request.urlopen(origin+'/api/status') as response:state=json.load(response)
            self.assertEqual(state['last_error'],collector.last_error)
            with urllib.request.urlopen(origin+'/dashboard.js') as response:
                self.assertEqual(response.headers.get_content_type(),'text/javascript')
                self.assertIn(b'visibilitychange',response.read())
            with urllib.request.urlopen(origin+'/reference-image.js') as response:
                self.assertEqual(response.headers.get_content_type(),'text/javascript')
                self.assertIn(b'AIEdgeReferenceImage',response.read())
            with urllib.request.urlopen(origin+'/app.css') as response:
                self.assertEqual(response.headers.get_content_type(),'text/css')
                self.assertIn(b'color-scheme',response.read())
            with urllib.request.urlopen(origin+'/favicon.svg') as response:
                self.assertEqual(response.headers.get_content_type(),'image/svg+xml')
                self.assertIn(b'<svg',response.read())
        finally:server.shutdown();thread.join();server.server_close()
    def test_http_marker_suggestions_preserve_calibration_and_runtime(self):
        saved=self.setup.save(self.ref,DESIGN,None);before=self.setup.path.read_bytes();pipeline=self.worker.reader.pipeline_id
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.store,False,None,self.worker,self.setup))
        thread=threading.Thread(target=server.serve_forever);thread.start();origin='http://127.0.0.1:'+str(server.server_port)
        try:
            with urllib.request.urlopen(origin+'/api/setup') as response:token=json.load(response)['token']
            request=urllib.request.Request(origin+'/api/setup/suggest-markers',data=json.dumps({'reference_sha256':self.ref,'crops':[DESIGN['dials'][0]['crop']]}).encode(),headers={'Content-Type':'application/json','X-AIEdge-Setup':token},method='POST')
            with urllib.request.urlopen(request) as response:result=json.load(response)
            self.assertEqual(result['markers'],[]);self.assertFalse(result['automatic_calibration'])
            self.assertEqual(self.setup.path.read_bytes(),before);self.assertEqual(self.setup.status(),saved)
            self.assertEqual(self.worker.reader.pipeline_id,pipeline)
        finally:server.shutdown();thread.join();server.server_close()
    def test_http_setup_round_trip_and_request_protection(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.store,False,None,self.worker,self.setup));thread=threading.Thread(target=server.serve_forever);thread.start();origin='http://127.0.0.1:'+str(server.server_port)
        def post(path,body,token=None,extra=None):
            headers={'Content-Type':'application/json'}
            if token:headers['X-AIEdge-Setup']=token
            headers.update(extra or {})
            request=urllib.request.Request(origin+path,data=body,headers=headers,method='POST')
            try:
                with urllib.request.urlopen(request) as r:return r.status,json.load(r)
            except urllib.error.HTTPError as e:code=e.code;e.close();return code,None
        try:
            with urllib.request.urlopen(origin+'/api/setup') as response:initial=json.load(response)
            payload=json.dumps({'reference_sha256':self.ref,'design':DESIGN,'revision':None}).encode()
            self.assertEqual(post('/api/setup/save',b'')[0],403)
            self.assertEqual(post('/api/setup/save',b'['*2000+b']'*2000,initial['token'])[0],400)
            self.assertEqual(post('/api/setup/save',b'',initial['token'],{'Host':'evil.example'})[0],403)
            code,saved=post('/api/setup/save',payload,initial['token']);self.assertEqual(code,200);self.assertIsNotNone(saved['revision'])
            self.assertEqual(post('/api/setup/save',payload,initial['token'])[0],400)
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port)
            connection.request('POST','/api/setup/reference',headers={'Content-Length':str(4*1024*1024+1),'X-AIEdge-Setup':initial['token']})
            self.assertEqual(connection.getresponse().status,400);connection.close()
            with urllib.request.urlopen(origin+'/reference/'+self.ref) as response:self.assertEqual(response.read(),reference())
        finally:server.shutdown();thread.join();server.server_close()
if __name__=='__main__':unittest.main()
