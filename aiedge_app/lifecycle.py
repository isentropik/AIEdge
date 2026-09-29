"""Bounded worker shutdown for normal app stops and Supervisor SIGTERM."""
import signal, threading, time

class ServiceRuntime:
    def __init__(self, server, workers, timeout=25):
        self.server=server;self.workers=[worker for worker in workers if worker]
        self.timeout=timeout;self.stopping=threading.Event();self.threads=[]
        self.ready=threading.Event()

    def request_stop(self, *_):
        if self.stopping.is_set():return
        self.stopping.set()
        for worker in self.workers:worker.stop.set()
        if hasattr(self.server,'begin_shutdown'):self.server.begin_shutdown()
        # HTTPServer.shutdown cannot run on the serve_forever thread itself.
        threading.Thread(target=self.server.shutdown,daemon=True).start()

    def run(self):
        old_handlers={};requests_drained=True
        if threading.current_thread() is threading.main_thread():
            for name in (signal.SIGINT,signal.SIGTERM):
                old_handlers[name]=signal.signal(name,self.request_stop)
        try:
            for worker in self.workers:
                thread=threading.Thread(target=worker.run,daemon=True)
                self.threads.append(thread);thread.start()
            self.ready.set()
            self.server.serve_forever(poll_interval=.1)
        finally:
            self.stopping.set()
            for worker in self.workers:worker.stop.set()
            deadline=time.monotonic()+self.timeout
            self.server.server_close()
            if hasattr(self.server,'drain_requests'):
                requests_drained=self.server.drain_requests(max(0,deadline-time.monotonic()))
            for thread in self.threads:thread.join(max(0,deadline-time.monotonic()))
            for name,previous in old_handlers.items():signal.signal(name,previous)
        return requests_drained and not any(thread.is_alive() for thread in self.threads)
