import json,threading,tempfile,unittest,urllib.request,urllib.error
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch
from capture import Store
from archive import Archive
from service import handler

class ArchiveHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(self.temp.name);self.archive=Archive(self.store)
        setup=SimpleNamespace(status=lambda:{'revision':None,'calibration':None})
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.store,False,None,setup=setup,archive=self.archive));self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
        self.origin='http://127.0.0.1:'+str(self.server.server_port);self.token=self.request('/api/setup')[1]['token']
    def tearDown(self):self.server.shutdown();self.thread.join();self.server.server_close();self.temp.cleanup()
    def request(self,path,payload=None,token=None,host=None):
        headers={'Content-Type':'application/json'}
        if token is not None:headers['X-AIEdge-Setup']=token
        if host:headers['Host']=host
        request=urllib.request.Request(self.origin+path,data=json.dumps(payload).encode() if payload else None,headers=headers)
        try:
            with urllib.request.urlopen(request,timeout=2) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as error:
            with error:return error.code,json.load(error) if error.headers.get_content_type()=='application/json' else None
    def payload(self):return {'action':'save','config':{'enabled':True,'directory':'/media/fixture'},'revision':self.archive.status()['revision']}
    def test_csrf_origin_and_unrecognized_actions_rejected(self):
        for token,host in ((None,None),('wrong',None),(self.token,'evil.invalid')):
            self.assertEqual(self.request('/api/archive',self.payload(),token,host)[0],403)
        self.assertEqual(self.request('/api/archive',{'action':'format'},self.token)[0],400)
        self.assertEqual(self.archive.status()['state'],'disabled')
    def test_save_readback_and_conflict_do_not_touch_network(self):
        original=self.payload()
        with patch('archive_copy.MountedFilesystem',side_effect=AssertionError('NAS I/O in HTTP')):
            self.assertEqual(self.request('/api/archive',original,self.token)[0],200)
            code,state=self.request('/api/archive');self.assertEqual(code,200);self.assertTrue(state['config']['enabled'])
            self.assertEqual(self.request('/api/archive',original,self.token)[0],409)
    def test_diagnostics_omits_server_path_and_archive_metadata(self):
        self.request('/api/archive',self.payload(),self.token)
        code,state=self.request('/api/diagnostics');self.assertEqual(code,200)
        self.assertNotIn('/media/fixture',json.dumps(state));self.assertNotIn(self.archive.instance,json.dumps(state))
        self.assertEqual(state['archive']['state'],'waiting_for_capture')

if __name__=='__main__':unittest.main()
