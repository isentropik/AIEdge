import json
import threading
import unittest
import urllib.request
import urllib.error
from types import SimpleNamespace
from http.server import ThreadingHTTPServer
from service import handler
import test_image_retention as fixtures


class RetentionHttpTests(unittest.TestCase):
    def setUp(self):
        fixtures.ImageRetentionTests.setUp(self)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.store,False,None,
            setup=SimpleNamespace(status=lambda:{}),retention=self.worker))
        self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
        self.addCleanup(self.close)
        self.origin='http://127.0.0.1:'+str(self.server.server_port)
        self.token=self.get('/api/setup')['token']

    def close(self):self.server.shutdown();self.thread.join();self.server.server_close()
    def get(self,path):
        with urllib.request.urlopen(self.origin+path,timeout=5) as response:return json.load(response)
    def post(self,data,token=None):
        request=urllib.request.Request(self.origin+'/api/retention',data=json.dumps(data).encode(),
            headers={'Content-Type':'application/json','X-AIEdge-Setup':token or ''})
        with urllib.request.urlopen(request,timeout=5) as response:return json.load(response)

    def test_read_save_readback_and_conflict(self):
        original=self.get('/api/retention')
        data=dict(config=dict(recent_events=20,older_images=10,older_megabytes=1),revision=original['revision'])
        saved=self.post(data,self.token)
        self.assertEqual(saved['config'],self.get('/api/retention')['config'])
        with self.assertRaises(urllib.error.HTTPError) as error:self.post(data,self.token)
        self.assertEqual(error.exception.code,400)

    def test_token_required_no_write(self):
        data=dict(config=dict(recent_events=1,older_images=0,older_megabytes=0),revision='default')
        with self.assertRaises(urllib.error.HTTPError) as error:self.post(data)
        self.assertEqual(error.exception.code,403)
        self.assertEqual(self.get('/api/retention')['revision'],'default')

    def test_invalid_and_corrupt_no_defaults_overwrite(self):
        data=dict(config=dict(recent_events=True,older_images=0,older_megabytes=0),revision='default')
        with self.assertRaises(urllib.error.HTTPError):self.post(data,self.token)
        (self.root/'image-retention.json').write_text('{')
        with self.assertRaises(urllib.error.HTTPError) as error:self.get('/api/retention')
        self.assertEqual(error.exception.code,503)
        self.assertEqual((self.root/'image-retention.json').read_text(),'{')


if __name__=='__main__':unittest.main()
