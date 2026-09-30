import json,threading,unittest,urllib.request,urllib.error
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from service import handler
import test_reviews

class HttpReviewTests(unittest.TestCase):
    payload=test_reviews.ReviewTests.payload
    # Exercise only HTTP cases here; backend cases run in test_reviews.
    def setUp(self):
        test_reviews.ReviewTests.setUp(self)
        setup=SimpleNamespace(status=lambda:{'revision':None,'calibration':None})
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.store,False,None,setup=setup,reviews=self.reviews))
        self.thread=threading.Thread(target=self.server.serve_forever);self.thread.start()
        self.origin='http://127.0.0.1:'+str(self.server.server_port)
        self.token=self.get('/api/setup')[1]['token']
    def tearDown(self):self.server.shutdown();self.thread.join();self.server.server_close();test_reviews.ReviewTests.tearDown(self)
    def get(self,path):
        try:
            with urllib.request.urlopen(self.origin+path) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as error:
            with error:return error.code,json.load(error) if error.headers.get_content_type()=='application/json' else None
    def post(self,payload,token=None,host=None):
        headers={'Content-Type':'application/json'}
        if token is not None:headers['X-AIEdge-Setup']=token
        if host:headers['Host']=host
        request=urllib.request.Request(self.origin+'/api/reviews',data=json.dumps(payload).encode(),headers=headers,method='POST')
        try:
            with urllib.request.urlopen(request) as response:return response.status,json.load(response)
        except urllib.error.HTTPError as error:
            with error:return error.code,json.load(error) if error.headers.get_content_type()=='application/json' else None
    def test_http_saved_review_roundtrip_and_history_summary(self):
        payload=self.payload();code,saved=self.post(payload,self.token);self.assertEqual(code,200)
        code,state=self.get('/api/reviews/1');self.assertEqual(code,200);self.assertEqual(state['review'],saved)
        code,page=self.get('/api/capture-history');self.assertEqual(code,200);self.assertEqual(page['items'][0]['reviewed_dials'],1)
        with urllib.request.urlopen(self.origin+'/capture-review.js') as response:self.assertIn(b'AIEdgeReview',response.read())
    def test_http_review_csrf_and_origin_rejection(self):
        payload=self.payload()
        self.assertEqual(self.post(payload)[0],403)
        self.assertEqual(self.post(payload,'invalid')[0],403)
        self.assertEqual(self.post(payload,self.token,'evil.example')[0],403)
        self.assertIsNone(self.reviews.get(1)['review'])
    def test_http_conflict_bad_capture_and_malformed_review_are_explicit(self):
        payload=self.payload();self.assertEqual(self.post(payload,self.token)[0],200)
        code,error=self.post(payload,self.token);self.assertEqual(code,409);self.assertEqual(error['code'],'review_conflict')
        self.assertEqual(self.get('/api/reviews/2')[0],404)
        self.assertEqual(self.get('/api/reviews/not-an-id')[0],400)
        self.assertEqual(self.post({'event_id':1},self.token)[0],400)

if __name__=='__main__':unittest.main()
