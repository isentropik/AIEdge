import socket,threading,time,unittest,urllib.request
from http.server import BaseHTTPRequestHandler
from http_server import AppHTTPServer
from lifecycle import ServiceRuntime

class HttpLifecycleTests(unittest.TestCase):
    def server(self,blocked=False):
        started=threading.Event();release=threading.Event();finished=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                started.set()
                if blocked:release.wait(3)
                try:self.send_response(200);self.end_headers();self.wfile.write(b'ok')
                except OSError:pass
                finally:finished.set()
        server=AppHTTPServer(('127.0.0.1',0),Handler)
        return server,started,release,finished
    def start(self,server,timeout=1,workers=()):
        runtime=ServiceRuntime(server,workers,timeout=timeout);results=[]
        thread=threading.Thread(target=lambda:results.append(runtime.run()));thread.start()
        self.assertTrue(runtime.ready.wait(2))
        return runtime,thread,results
    def connect(self,server,complete=True):
        client=socket.create_connection(('127.0.0.1',server.server_port),timeout=2)
        client.sendall(b'GET / HTTP/1.0\r\nHost: localhost\r\n'+(b'\r\n' if complete else b''))
        return client
    def wait_active(self,server):
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            with server._request_condition:
                if server._requests:return
            time.sleep(.005)
        self.fail('Request was not admitted')
    def test_stop_drains_an_inflight_http_handler(self):
        server,started,release,finished=self.server(True);runtime,thread,result=self.start(server)
        client=self.connect(server)
        try:
            self.assertTrue(started.wait(2));runtime.request_stop()
            thread.join(.15);self.assertTrue(thread.is_alive());self.assertFalse(finished.is_set())
            release.set();thread.join(2)
            self.assertFalse(thread.is_alive());self.assertTrue(finished.is_set());self.assertEqual(result,[True])
            self.assertIn(b'200 OK',client.recv(4096))
        finally:client.close();release.set();runtime.request_stop();thread.join(2)
    def test_incomplete_header_has_a_bounded_shutdown(self):
        server,_,release,_=self.server();runtime,thread,result=self.start(server,timeout=.1)
        client=self.connect(server,False)
        try:
            self.wait_active(server);start=time.monotonic();runtime.request_stop();thread.join(2)
            self.assertFalse(thread.is_alive());self.assertLess(time.monotonic()-start,1)
            self.assertEqual(result,[False])
        finally:client.close();release.set();runtime.request_stop();thread.join(2)
    def test_idle_header_times_out_without_stopping_the_service(self):
        server,_,release,_=self.server();server.request_timeout=.1
        runtime,thread,result=self.start(server);client=self.connect(server,False)
        try:
            self.assertEqual(client.recv(4096),b'')
            with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}/',timeout=2) as response:self.assertEqual(response.read(),b'ok')
            runtime.request_stop();thread.join(2);self.assertEqual(result,[True])
        finally:client.close();release.set();runtime.request_stop();thread.join(2)
    def test_connection_limit_does_not_start_unbounded_handlers(self):
        server,started,release,_=self.server(True);server.max_active_requests=1
        runtime,thread,result=self.start(server);first=self.connect(server);second=None
        try:
            self.assertTrue(started.wait(2));second=self.connect(server)
            try:data=second.recv(4096)
            except ConnectionError:data=b''
            self.assertEqual(data,b'')
            with server._request_condition:self.assertEqual(len(server._requests),1)
            release.set();first.recv(4096);runtime.request_stop();thread.join(2);self.assertEqual(result,[True])
        finally:
            first.close()
            if second:second.close()
            release.set();runtime.request_stop();thread.join(2)
    def test_http_and_workers_share_one_shutdown_budget(self):
        class Worker:
            def __init__(self):self.stop=threading.Event();self.release=threading.Event()
            def run(self):self.release.wait(3)
        worker=Worker();server,_,release,_=self.server()
        runtime,thread,result=self.start(server,timeout=.2,workers=[worker]);client=self.connect(server,False)
        try:
            self.wait_active(server);start=time.monotonic();runtime.request_stop();thread.join(2)
            self.assertLess(time.monotonic()-start,.55);self.assertEqual(result,[False])
        finally:
            client.close();release.set();worker.release.set();runtime.request_stop();thread.join(2)
            for task in runtime.threads:task.join(2)

if __name__=='__main__':unittest.main()
