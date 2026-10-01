"""Bound HTTP headers and body reads by one monotonic I/O deadline.

DNS and the initial connection still use the platform resolver/socket timeout;
this does not promise to interrupt a blocked operating-system DNS resolver.
"""
import errno,functools,http.client,socket,sys,time,urllib.request

# Small camera JPEGs benefit more from avoiding oversized radio packets than
# from filling each Ethernet-sized segment. This is a per-connection admission
# setting, not a change to the device, host interface or network MTU.
CAMERA_TCP_MAXSEG=512

def camera_connection(address,timeout=socket._GLOBAL_DEFAULT_TIMEOUT,source_address=None,*,deadline):
    last_error=None
    for family,kind,protocol,_,destination in socket.getaddrinfo(address[0],address[1],0,socket.SOCK_STREAM):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('camera_io_deadline')
        connection=None
        try:
            connection=socket.socket(family,kind,protocol)
            connection.settimeout(min(remaining,timeout) if isinstance(timeout,(int,float)) else remaining)
            if sys.platform.startswith('linux') and hasattr(socket,'TCP_MAXSEG'):
                try:connection.setsockopt(socket.IPPROTO_TCP,socket.TCP_MAXSEG,CAMERA_TCP_MAXSEG)
                except OSError as error:
                    if error.errno not in (errno.ENOPROTOOPT,errno.EOPNOTSUPP):raise
            if source_address:connection.bind(source_address)
            connection.connect(destination)
            return connection
        except OSError as error:
            last_error=error
            if connection is not None:connection.close()
    if last_error is not None:raise last_error
    raise OSError('camera_address_unavailable')

class DeadlineStream:
    def __init__(self,stream,sock,deadline):
        self.stream,self.socket,self.deadline=stream,sock,deadline
        self.buffer=bytearray()
    def _check(self):
        remaining=self.deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('camera_io_deadline')
        # The capture already has one absolute deadline. A separate five-second
        # idle cap rejected otherwise valid responses before that deadline.
        self.socket.settimeout(remaining)
    def read1(self,size=-1):
        self._check()
        if self.buffer:
            count=len(self.buffer) if size<0 else min(size,len(self.buffer))
            result=bytes(self.buffer[:count]);del self.buffer[:count];return result
        result=self.stream.read1(size)
        self._check();return result
    def readline(self,limit=-1):
        if limit==0:return b''
        while True:
            self._check()
            newline=self.buffer.find(b'\n')
            count=newline+1 if newline>=0 else 0
            if limit>=0 and (count>limit or len(self.buffer)>=limit):count=limit
            if count:
                result=bytes(self.buffer[:count]);del self.buffer[:count];return result
            block=self.stream.read1(65536)
            if not block:
                result=bytes(self.buffer);self.buffer.clear();return result
            self.buffer.extend(block)
    def read(self,size=-1):
        parts=[];remaining=size
        while remaining!=0:
            block=self.read1(65536 if remaining<0 else min(65536,remaining))
            if not block:break
            parts.append(block)
            if remaining>0:remaining-=len(block)
        return b''.join(parts)
    def close(self):self.buffer.clear();self.stream.close()
    @property
    def closed(self):return self.stream.closed
    def __getattr__(self,name):return getattr(self.stream,name)

class DeadlineResponse(http.client.HTTPResponse):
    def __init__(self,sock,*args,deadline,**kwargs):
        super().__init__(sock,*args,**kwargs)
        self.fp=DeadlineStream(self.fp,sock,deadline)

class DeadlineConnection(http.client.HTTPConnection):
    def __init__(self,*args,deadline,**kwargs):
        super().__init__(*args,**kwargs)
        self._create_connection=functools.partial(camera_connection,deadline=deadline)
        self.response_class=functools.partial(DeadlineResponse,deadline=deadline)

class DeadlineTLSConnection(http.client.HTTPSConnection):
    def __init__(self,*args,deadline,**kwargs):
        super().__init__(*args,**kwargs)
        self._create_connection=functools.partial(camera_connection,deadline=deadline)
        self.response_class=functools.partial(DeadlineResponse,deadline=deadline)

class DeadlineHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self,request):
        return self.do_open(functools.partial(DeadlineConnection,deadline=request.aiedge_deadline),request)

class DeadlineHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self,request):
        return self.do_open(functools.partial(DeadlineTLSConnection,deadline=request.aiedge_deadline),request,
                            context=self._context)
