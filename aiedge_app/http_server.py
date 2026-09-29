"""Bounded HTTP connections and request draining for an app stop."""
import socket,threading,time,sys
from http.server import ThreadingHTTPServer

class AppHTTPServer(ThreadingHTTPServer):
    daemon_threads=True
    request_timeout=10
    max_active_requests=32

    def __init__(self,*args,**kwargs):
        self._requests=set();self._request_condition=threading.Condition();self._draining=False
        super().__init__(*args,**kwargs)

    def get_request(self):
        request,address=super().get_request()
        request.settimeout(self.request_timeout)
        return request,address

    def process_request(self,request,address):
        with self._request_condition:
            admitted=not self._draining and len(self._requests)<self.max_active_requests
            if admitted:self._requests.add(request)
        if not admitted:
            self.shutdown_request(request)
            return
        try:super().process_request(request,address)
        except BaseException:
            self._finished(request)
            raise

    def _finished(self,request):
        with self._request_condition:
            self._requests.discard(request);self._request_condition.notify_all()

    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self._finished(request)

    def handle_error(self,request,address):
        # Peer disconnects, including sockets closed at the drain deadline, are
        # expected transport events rather than application tracebacks.
        if isinstance(sys.exc_info()[1],(ConnectionError,TimeoutError)):return
        super().handle_error(request,address)

    def begin_shutdown(self):
        with self._request_condition:self._draining=True

    def drain_requests(self,timeout):
        self.begin_shutdown();deadline=time.monotonic()+max(0,timeout)
        with self._request_condition:
            while self._requests:
                remaining=deadline-time.monotonic()
                if remaining<=0:break
                self._request_condition.wait(remaining)
            if not self._requests:return True
            outstanding=list(self._requests)
        # Break stalled reads/writes. CPU-bound handlers cannot be forcibly made
        # safe; return failure and let process shutdown enforce the final limit.
        for request in outstanding:
            try:request.shutdown(socket.SHUT_RDWR)
            except OSError:pass
        return False
