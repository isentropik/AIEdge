"""Bounded worker shutdown for normal app stops and Supervisor SIGTERM."""
import json, signal, threading, time

SHUTDOWN_TIMEOUT_SECONDS=35

def lifecycle_event(event, **fields):
    """Stdout only; bounded diagnostics with no credentials or SD writes."""
    print(json.dumps({'event':event, **fields},allow_nan=False),flush=True)

class StartupStopped(Exception):
    """A requested stop reached a safe initialization boundary."""

class StartupSignals:
    """Receive stop requests before importing/loading the recognition engine.

    Signal callbacks record intent and forward it to an attached runtime. They
    do not log or perform storage writes. Initialization is allowed to finish
    its current operation, then exits at a checkpoint without starting capture.
    """
    def __init__(self):
        self.stopping=threading.Event();self.requested=False;self.runtime=None;self.old_handlers={}
    def __enter__(self):
        if threading.current_thread() is threading.main_thread():
            for name in (signal.SIGINT,signal.SIGTERM):
                self.old_handlers[name]=signal.signal(name,self.request_stop)
        return self
    def request_stop(self,*_):
        if self.requested:return
        self.requested=True
        self.stopping.set()
        if self.runtime is not None:self.runtime.request_stop()
    def checkpoint(self):
        if self.stopping.is_set():raise StartupStopped()
    def attach(self,runtime):
        self.runtime=runtime
        if self.stopping.is_set():runtime.request_stop()
    def __exit__(self,*_):
        self.runtime=None
        for name,previous in self.old_handlers.items():signal.signal(name,previous)

class ServiceRuntime:
    def __init__(self, server, workers, timeout=SHUTDOWN_TIMEOUT_SECONDS, signals=None):
        self.server=server;self.workers=[worker for worker in workers if worker]
        self.timeout=timeout;self.stopping=threading.Event();self.threads=[]
        self.ready=threading.Event()
        self.signals=signals;self.serving=False;self.shutdown_thread=None
        self.stop_started=False;self.stop_lock=threading.RLock()

    def request_stop(self, *_):
        with self.stop_lock:
            if self.stop_started:return
            # Mark intent before Event.set: a second signal on the same thread
            # must not reenter the event's non-reentrant internal lock.
            self.stop_started=True
            self.stopping.set()
            for worker in self.workers:worker.stop.set()
            if hasattr(self.server,'begin_shutdown'):self.server.begin_shutdown()
            # HTTPServer.shutdown cannot run on the serve_forever thread itself.
            # Before serving, run() closes without starting a blocked shutdown.
            if self.serving:
                self.shutdown_thread=threading.Thread(target=self.server.shutdown,daemon=True)
                self.shutdown_thread.start()

    def run(self):
        old_handlers={};requests_drained=True
        if self.signals is not None:self.signals.attach(self)
        elif threading.current_thread() is threading.main_thread():
            for name in (signal.SIGINT,signal.SIGTERM):
                old_handlers[name]=signal.signal(name,self.request_stop)
        try:
            for worker in self.workers:
                if self.stopping.is_set():break
                thread=threading.Thread(target=worker.run,daemon=True)
                self.threads.append(thread);thread.start()
            self.serving=True
            # Recheck after the serving flag is set: a stop just before it
            # must not leave an HTTP loop running without a shutdown request.
            if not self.stopping.is_set():
                self.ready.set()
                lifecycle_event('aiedge_ready',workers=len(self.threads))
                self.server.serve_forever(poll_interval=.1)
        finally:
            self.serving=False
            self.request_stop()
            started=time.monotonic()
            deadline=time.monotonic()+self.timeout
            self.server.server_close()
            if hasattr(self.server,'drain_requests'):
                requests_drained=self.server.drain_requests(max(0,deadline-time.monotonic()))
            for thread in self.threads:thread.join(max(0,deadline-time.monotonic()))
            if self.shutdown_thread:self.shutdown_thread.join(max(0,deadline-time.monotonic()))
            for name,previous in old_handlers.items():signal.signal(name,previous)
        complete=requests_drained and not any(thread.is_alive() for thread in self.threads) and not (self.shutdown_thread and self.shutdown_thread.is_alive())
        lifecycle_event('aiedge_stopped' if complete else 'aiedge_shutdown_timeout',requests_drained=requests_drained,
                        pending_workers=sum(thread.is_alive() for thread in self.threads),duration_seconds=round(time.monotonic()-started,3))
        return bool(complete)
