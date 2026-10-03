import hashlib
import copy
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.message import Message
from http.server import ThreadingHTTPServer

from capture import Camera, Store, io_deadline
from capture_trial import CaptureTrial
from service import handler

JPEG = b'\xff\xd8trial-transport-envelope\xff\xd9'
ID = 'a' * 32

class Clock:
    def __init__(self):self.value = time.monotonic()
    def __call__(self):return self.value
    def wait(self, seconds):self.value += seconds

def headers(index, blob=JPEG, *, clock_id='trial-clock', missing_clock=False):
    h = Message()
    h['X-AIEdge-Frame-Id'] = 'trial-' + str(index)
    h['X-AIEdge-Captured-At'] = (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index*30)).isoformat()
    h['X-AIEdge-SHA256'] = hashlib.sha256(blob).hexdigest()
    if not missing_clock:
        h['X-AIEdge-Clock-Id'] = clock_id
        h['X-AIEdge-Capture-Monotonic-Us'] = str(index*30_000_000)
    return h

class FakeCamera:
    origin = 'http://127.0.0.1'
    def __init__(self):self.calls = 0;self.checks = 0;self.lock = threading.Lock();self.hook = None
    @contextmanager
    def operation(self):
        if not self.lock.acquire(False):raise ValueError('camera_busy')
        try:yield
        finally:self.lock.release()
    def require_capture(self):pass
    def readiness(self, deadline=None):self.checks += 1;return {'state':'ready'}
    def capture(self, *, deadline=None):
        self.calls += 1
        return self.hook(self.calls, deadline) if self.hook else (JPEG, headers(self.calls))

class TrialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.clock = Clock()
        self.camera = FakeCamera()
        self.allowed = True
        self.context = {'pipeline_id':'c'*64, 'format_revision':'d'*64}
        self.worker = self.make_worker()
        self.worker.recover()
    def tearDown(self):self.temp.cleanup()
    def make_worker(self):
        return CaptureTrial(self.store, self.camera, lambda:self.allowed, context=lambda:self.context,
                            clock=self.clock, wait=self.clock.wait)
    def start(self, **kwargs):return self.worker.start(ID, **kwargs)

    def test_three_attempts_and_duplicates_never_enable_training_or_repeat(self):
        self.start();self.assertTrue(self.worker.once())
        state = self.worker.status()
        self.assertEqual((state['state'], state['attempts'], state['saved_frames'], state['unique_images'], state['duplicate_images']),
                         ('completed',3,3,1,2))
        self.assertEqual(self.camera.calls,3)
        self.assertEqual(self.store.status()['captures'],3)
        self.assertFalse(state['training_allowed']);self.assertFalse(state['accuracy_verified'])
        self.assertFalse(self.worker.once());self.assertEqual(self.start(),state)
        self.assertEqual(self.camera.calls,3)
        self.assertTrue(all(not row['training_allowed'] for row in self.store.history()['items']))
        self.assertEqual(self.store.capture_timing()['elapsed_seconds'],30)

    def test_time_budget_prevents_more_requests_and_never_catches_up(self):
        self.start(duration_seconds=50);self.worker.once()
        self.assertEqual((self.camera.calls,self.worker.status()['state']), (2,'expired'))
        new = self.make_worker();new.recover()
        self.assertEqual(new.start(ID,duration_seconds=50)['state'],'expired')
        self.assertFalse(new.once());self.assertEqual(self.camera.calls,2)

    def test_missed_slots_do_not_create_a_burst(self):
        def slow(index, deadline):self.clock.value += 35;return JPEG,headers(index)
        self.camera.hook = slow
        self.start();self.worker.once()
        self.assertEqual(self.camera.calls,2)
        self.assertEqual(self.worker.status()['missed_slots'],2)
        self.assertEqual(self.worker.status()['state'],'expired')

    def test_cancel_before_start_and_during_capture(self):
        self.start();self.worker.cancel(ID);self.assertFalse(self.worker.once())
        self.assertEqual(self.camera.calls,0)
        other='b'*32
        self.worker.start(other)
        def cancel(index, deadline):
            self.worker.cancel(other)
            self.assertEqual(self.worker.status()['state'],'cancelling')
            self.assertTrue(self.worker.status()['in_flight'])
            return JPEG,headers(index)
        self.camera.hook=cancel;self.worker.once()
        self.assertEqual((self.camera.calls,self.worker.status()['saved_frames'],self.worker.status()['state']), (1,1,'cancelled'))

    def test_restart_consumes_queued_and_uncertain_inflight_request(self):
        queued=self.start()
        new=self.make_worker();new.recover()
        state=new.start(ID)
        self.assertEqual(state['state'],'interrupted');self.assertFalse(state['counts_complete'])
        self.assertFalse(new.once());self.assertEqual(self.camera.calls,0)
        # Simulate a process dying after durable POST admission, before response.
        state=dict(queued,state='working',attempts=1,in_flight=True)
        new._write(state)
        restarted=self.make_worker();restarted.recover()
        state=restarted.start(ID)
        self.assertEqual(state['state'],'interrupted');self.assertTrue(state['capture_outcome_uncertain'])
        self.assertFalse(restarted.once());self.assertEqual(self.camera.calls,0)

    def test_failure_never_retries_or_exposes_private_error(self):
        def fail(index, deadline):raise TimeoutError('password and secret URL must stay private')
        self.camera.hook=fail;self.start();self.worker.once()
        state=self.worker.status()
        self.assertEqual((state['state'],state['attempts'],state['error']),('failed',1,'trial_capture_failed'))
        self.assertTrue(state['capture_outcome_uncertain']);self.assertNotIn('secret',json.dumps(state))
        self.start();self.worker.once();self.assertEqual(self.camera.calls,1)

    def test_context_change_and_invalid_clock_preserve_verified_raw(self):
        def changed(index,deadline):
            self.context={'pipeline_id':'e'*64};return JPEG,headers(index)
        self.camera.hook=changed;self.start();self.worker.once()
        self.assertEqual(self.worker.status()['error'],'trial_context_changed')
        self.assertEqual(self.store.status()['captures'],1)
        self.assertEqual(self.camera.calls,1)
        self.camera.hook=lambda index,deadline:(JPEG,headers(index,missing_clock=True))
        self.worker.start('b'*32);self.worker.once()
        self.assertEqual(self.worker.status()['error'],'trial_clock_unverified')
        self.assertEqual(self.store.status()['captures'],2)

    def test_invalid_limits_conflicts_busy_and_disabled_have_no_camera_io(self):
        for field,value in [('max_attempts',4),('max_attempts',True),('duration_seconds',91),
                            ('duration_seconds',float('nan')),('interval_seconds',0)]:
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):self.start(**{field:value})
        self.allowed=False
        with self.assertRaisesRegex(ValueError,'trial_not_allowed'):self.start()
        self.allowed=True;self.start()
        with self.assertRaisesRegex(ValueError,'trial_busy'):self.worker.start('b'*32)
        with self.assertRaisesRegex(ValueError,'trial_request_conflict'):self.start(max_attempts=1)
        self.allowed=False;self.worker.once()
        self.assertEqual(self.worker.status()['error'],'trial_not_allowed')
        self.assertEqual(self.camera.calls,0)

    def test_expired_deadline_or_camera_busy_never_starts_post(self):
        self.start();self.clock.value += 90;self.worker.once()
        self.assertEqual(self.worker.status()['state'],'expired');self.assertEqual(self.camera.calls,0)
        self.worker.start('b'*32);self.camera.lock.acquire()
        try:self.worker.once()
        finally:self.camera.lock.release()
        self.assertEqual(self.worker.status()['error'],'camera_busy');self.assertEqual(self.camera.calls,0)
        with self.assertRaisesRegex(ValueError,'capture_deadline_exceeded'):io_deadline(20,time.monotonic()-1)
        with self.assertRaisesRegex(ValueError,'camera_deadline_invalid'):io_deadline(20,True)

    def test_readiness_may_expire_or_change_context_without_a_capture_post(self):
        def expired(deadline=None):self.clock.value+=91;return {'state':'ready'}
        self.camera.readiness=expired;self.start();self.worker.once()
        self.assertEqual(self.worker.status()['state'],'expired');self.assertEqual(self.camera.calls,0)
        def changed(deadline=None):self.context={};return {'state':'ready'}
        self.camera.readiness=changed;self.worker.start('b'*32);self.worker.once()
        self.assertEqual(self.worker.status()['error'],'trial_context_changed');self.assertEqual(self.camera.calls,0)

    def test_clock_epoch_change_keeps_raw_frame_but_stops_trial(self):
        self.camera.hook=lambda index,deadline:(JPEG,headers(index,clock_id='changed' if index==2 else 'trial-clock'))
        self.start();self.worker.once()
        self.assertEqual(self.worker.status()['error'],'trial_frame_not_fresh')
        self.assertEqual(self.store.status()['captures'],2);self.assertEqual(self.camera.calls,2)

    def test_failed_journal_write_refuses_further_camera_io(self):
        from unittest.mock import patch
        import sqlite3
        self.start()
        with patch.object(self.store,'connect',side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(sqlite3.Error):self.worker.once()
        self.assertFalse(self.worker.ready)
        self.assertEqual(self.worker.status()['error'],'trial_storage_unavailable')
        with self.assertRaisesRegex(ValueError,'trial_not_ready'):self.worker.start('b'*32)
        self.assertEqual(self.camera.calls,0)

class CorruptTrialHTTPTests(unittest.TestCase):
    def test_corrupt_trial_journal_keeps_main_api_and_website_available(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);camera=FakeCamera()
            initial=CaptureTrial(store,camera,lambda:True);initial.recover();initial.start(ID)
            corrupt='{"request_id":"SECRET-should-never-escape"}'
            with store.connect() as db:db.execute('UPDATE capture_trials SET document=?',(corrupt,))
            trial=CaptureTrial(store,camera,lambda:True);trial.recover()
            class Setup:
                def status(self):return {'revision':None,'calibration':None}
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(store,False,None,setup=Setup(),trial=trial))
            thread=threading.Thread(target=server.serve_forever);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                with urllib.request.urlopen(base+'/',timeout=2) as response:
                    self.assertEqual(response.status,200);self.assertIn(b'AIEdge',response.read())
                with urllib.request.urlopen(base+'/api/status',timeout=2) as response:
                    main=json.load(response);self.assertEqual(main['captures'],0);self.assertFalse(main['capture_enabled'])
                with urllib.request.urlopen(base+'/api/capture-trial',timeout=2) as response:state=json.load(response)
                self.assertEqual(state['state'],'unavailable');self.assertEqual(state['error'],'trial_journal_invalid')
                self.assertTrue(state['capture_outcome_uncertain']);self.assertNotIn('SECRET',json.dumps(state))
                with urllib.request.urlopen(base+'/api/setup',timeout=2) as response:token=json.load(response)['token']
                request=urllib.request.Request(base+'/api/capture-trial',data=json.dumps(dict(action='start',request_id='b'*32,
                    max_attempts=3,duration_seconds=90,interval_seconds=30)).encode(),headers={'X-AIEdge-Setup':token,'Content-Type':'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as rejected:urllib.request.urlopen(request,timeout=2)
                self.assertEqual(rejected.exception.code,400);rejected.exception.close()
                self.assertEqual(camera.calls,0)
                with store.connect() as db:self.assertEqual(db.execute('SELECT document FROM capture_trials').fetchone()[0],corrupt)
            finally:server.shutdown();thread.join();server.server_close()

class JournalTests(unittest.TestCase):
    def fixture(self,folder,max_attempts=3):
        store=Store(folder);camera=FakeCamera();worker=CaptureTrial(store,camera,lambda:True)
        worker.recover();snapshot=worker.start(ID,max_attempts=max_attempts)
        return store,camera,worker,snapshot

    def test_malformed_records_fail_closed_without_rewrite_or_secret_disclosure(self):
        from capture_trial import MAX_JOURNAL_BYTES
        base=None
        with tempfile.TemporaryDirectory() as folder:_,_,_,base=self.fixture(folder)
        records=['{','[]','null',json.dumps(dict(base,request_id='b'*32)),
                 json.dumps(dict(base,attempts=True)),json.dumps(dict(base,max_attempts=4)),
                 json.dumps(dict(base,training_allowed=True)),json.dumps(dict(base,accuracy_verified=True)),
                 json.dumps(dict(base,finished_at='unparseable')),json.dumps(dict(base,state='secret-private')),
                 json.dumps(dict(base,context={'password':'SECRET'})),json.dumps(dict(base,saved_frames=1)),
                 json.dumps(dict(base,in_flight=True)),json.dumps(dict(base,error='SECRET')),
                 json.dumps(base)[:-1]+',"attempts":1}',json.dumps(dict(base,missed_slots=float('nan'))),
                 '['*6000+']'*6000,'SECRET'*(MAX_JOURNAL_BYTES//6+1)]
        for encoded in records:
            with self.subTest(case=records.index(encoded)),tempfile.TemporaryDirectory() as folder:
                store,camera,_,_=self.fixture(folder)
                with store.connect() as db:db.execute('UPDATE capture_trials SET document=?',(encoded,))
                restarted=CaptureTrial(store,camera,lambda:True);restarted.recover()
                self.assertFalse(restarted.ready);self.assertEqual(restarted.status()['error'],'trial_journal_invalid')
                self.assertNotIn('SECRET',json.dumps(restarted.status()))
                with self.assertRaisesRegex(ValueError,'trial_not_ready'):restarted.start('b'*32)
                self.assertFalse(restarted.once());self.assertEqual(camera.calls,0)
                with store.connect() as db:self.assertEqual(db.execute('SELECT document FROM capture_trials').fetchone()[0],encoded)

    def test_recovery_rolls_back_earlier_record_if_a_later_record_is_invalid(self):
        with tempfile.TemporaryDirectory() as folder:
            store,camera,_,snapshot=self.fixture(folder)
            with store.connect() as db:
                original=db.execute('SELECT document FROM capture_trials WHERE request_id=?',(ID,)).fetchone()[0]
                db.execute('INSERT INTO capture_trials VALUES(?,?)',('b'*32,'BROKEN-private'))
            restarted=CaptureTrial(store,camera,lambda:True);restarted.recover()
            self.assertEqual(restarted.status()['error'],'trial_journal_invalid');self.assertFalse(restarted.ready)
            with store.connect() as db:
                self.assertEqual(db.execute('SELECT document FROM capture_trials WHERE request_id=?',(ID,)).fetchone()[0],original)
            self.assertEqual(camera.calls,0)

    def test_completed_and_interrupted_v1_records_remain_consumed(self):
        for state in ('completed','cancelled','interrupted'):
            with self.subTest(state=state),tempfile.TemporaryDirectory() as folder:
                store,camera,worker,_=self.fixture(folder,max_attempts=1)
                if state=='completed':worker.once()
                elif state=='cancelled':worker.cancel(ID)
                else:worker=CaptureTrial(store,camera,lambda:True);worker.recover()
                first=worker.status();self.assertEqual(first['state'],state)
                with store.connect() as db:encoded=db.execute('SELECT document FROM capture_trials').fetchone()[0]
                restarted=CaptureTrial(store,camera,lambda:True);restarted.recover()
                self.assertEqual(restarted.start(ID,max_attempts=1),first);self.assertFalse(restarted.once())
                with store.connect() as db:self.assertEqual(db.execute('SELECT document FROM capture_trials').fetchone()[0],encoded)
                self.assertEqual(camera.calls,1 if state=='completed' else 0)

    def test_corruption_after_startup_and_deleted_admission_never_allow_new_post(self):
        with tempfile.TemporaryDirectory() as folder:
            store,camera,worker,_=self.fixture(folder);worker.cancel(ID)
            with store.connect() as db:db.execute('UPDATE capture_trials SET document=?',('BROKEN-private',))
            with self.assertRaisesRegex(ValueError,'trial_journal_invalid'):worker.start(ID)
            self.assertFalse(worker.ready);self.assertEqual(camera.calls,0)
        with tempfile.TemporaryDirectory() as folder:
            store,camera,worker,_=self.fixture(folder)
            with store.connect() as db:db.execute('DELETE FROM capture_trials')
            with self.assertRaisesRegex(ValueError,'trial_journal_invalid'):worker.once()
            self.assertEqual(worker.status()['error'],'trial_journal_invalid');self.assertEqual(camera.calls,0)

    def test_wrong_journal_schema_does_not_change_existing_capture_tables(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);camera=FakeCamera()
            store.add(camera.origin,JPEG,headers(1))
            with store.connect() as db:db.execute('CREATE TABLE capture_trials(unrelated TEXT)')
            worker=CaptureTrial(store,camera,lambda:True);worker.recover()
            self.assertEqual(worker.status()['error'],'trial_storage_unavailable')
            self.assertFalse(worker.ready);self.assertEqual(store.status()['captures'],1)
            self.assertEqual(store.image(hashlib.sha256(JPEG).hexdigest()),JPEG);self.assertEqual(camera.calls,0)

    def test_context_identifies_active_reader_before_any_image(self):
        from service import capture_trial_context
        from types import SimpleNamespace
        setup=SimpleNamespace(status=lambda:{'revision':'a'*64})
        formats=SimpleNamespace(status=lambda:{'revision':'b'*64})
        reader=SimpleNamespace(pipeline_id='c'*64)
        recognition=SimpleNamespace(lock=threading.Lock(),reader=reader,
            latest=lambda:(_ for _ in ()).throw(AssertionError('Latest inference must not define trial identity')))
        before=capture_trial_context(setup,recognition,formats)
        self.assertEqual(before['pipeline_id'],reader.pipeline_id)
        self.assertEqual(capture_trial_context(setup,recognition,formats),before)
        recognition.reader=SimpleNamespace(pipeline_id='d'*64)
        self.assertNotEqual(capture_trial_context(setup,recognition,formats),before)

class TrialLookupTests(unittest.TestCase):
    def test_lookup_retains_older_consumed_id_after_a_later_trial(self):
        with tempfile.TemporaryDirectory() as folder:
            camera=FakeCamera();worker=CaptureTrial(Store(folder),camera,lambda:True);worker.recover()
            worker.start(ID);worker.cancel(ID)
            worker.start('b'*32);worker.cancel('b'*32)
            self.assertEqual(worker.status()['request_id'],'b'*32)
            self.assertEqual(worker.status(ID)['state'],'cancelled')
            self.assertEqual(worker.status(ID)['request_id'],ID)
            recovered=CaptureTrial(worker.store,camera,lambda:True);recovered.recover()
            self.assertEqual(recovered.status(ID),worker.status(ID))
            self.assertEqual(recovered.status('c'*32)['state'],'not_found')
            self.assertEqual(camera.calls,0)

    def test_availability_is_advisory_and_never_performs_camera_io(self):
        with tempfile.TemporaryDirectory() as folder:
            camera=FakeCamera();permitted=[False]
            worker=CaptureTrial(Store(folder),camera,lambda:permitted[0])
            self.assertFalse(worker.availability()['can_start']);worker.recover()
            self.assertEqual(worker.availability()['block_reason'],'trial_not_allowed')
            permitted[0]=True;self.assertTrue(worker.availability()['can_start'])
            worker.start(ID);self.assertEqual(worker.availability()['block_reason'],'trial_busy')
            worker.cancel(ID);self.assertTrue(worker.availability()['can_start'])
            worker.stop.set();self.assertFalse(worker.availability()['can_start'])
            self.assertEqual(camera.calls,0)

    def test_query_lookup_errors_and_script_are_served_without_capture(self):
        class Setup:
            def status(self):return {}
        with tempfile.TemporaryDirectory() as folder:
            camera=FakeCamera();worker=CaptureTrial(Store(folder),camera,lambda:True);worker.recover()
            worker.start(ID);worker.cancel(ID);worker.start('b'*32);worker.cancel('b'*32)
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(worker.store,False,None,setup=Setup(),trial=worker))
            thread=threading.Thread(target=server.serve_forever);thread.start()
            origin=f'http://127.0.0.1:{server.server_port}'
            try:
                with urllib.request.urlopen(origin+'/api/capture-trial?request_id='+ID) as response:
                    result=json.load(response)
                self.assertEqual(result['request_id'],ID);self.assertEqual(result['state'],'cancelled')
                self.assertTrue(result['can_start'])
                for query in ('request_id=bad','request_id='+ID+'&request_id='+ID,'request_id=','other=x'):
                    with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(origin+'/api/capture-trial?'+query)
                    self.assertEqual(error.exception.code,400)
                with urllib.request.urlopen(origin+'/capture-trial.js') as response:
                    self.assertEqual(response.headers['Content-Type'],'text/javascript; charset=utf-8')
                    self.assertIn(b'X-AIEdge-Setup',response.read())
                self.assertEqual(camera.calls,0)
            finally:server.shutdown();thread.join();server.server_close()

class TrialHTTPTests(unittest.TestCase):
    def test_status_and_capture_share_one_deadline_even_for_a_slow_body(self):
        from http.server import BaseHTTPRequestHandler
        from test_camera_status import READY
        class Fixture(BaseHTTPRequestHandler):
            calls=0
            def log_message(self,*args):pass
            def do_GET(self):
                time.sleep(.4);body=json.dumps(READY).encode();self.send_response(200)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)))
                self.end_headers();self.wfile.write(body)
            def do_POST(self):
                Fixture.calls+=1;self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200);self.send_header('Content-Type','image/jpeg');self.send_header('Content-Length',str(len(JPEG)))
                for key,value in headers(Fixture.calls).items():self.send_header(key,value)
                self.end_headers();time.sleep(.8)
                try:self.wfile.write(JPEG)
                except (BrokenPipeError,ConnectionResetError):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                store=Store(folder);camera=Camera(f'http://127.0.0.1:{server.server_port}')
                trial=CaptureTrial(store,camera,lambda:True);trial.recover()
                trial.start(ID,duration_seconds=1);trial.once()
                self.assertEqual(trial.status()['state'],'failed',trial.status())
                self.assertEqual(trial.status()['error'],'camera_timeout')
                self.assertTrue(trial.status()['capture_outcome_uncertain'])
                self.assertEqual(store.status()['captures'],0);self.assertEqual(Fixture.calls,1)
                self.assertEqual(trial.start(ID,duration_seconds=1)['state'],'failed')
                self.assertFalse(trial.once());self.assertEqual(Fixture.calls,1)
        finally:server.shutdown();thread.join();server.server_close()

    def test_runtime_shutdown_preserves_only_inflight_frame_and_does_not_resume(self):
        from lifecycle import ServiceRuntime
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);camera=FakeCamera();trial=CaptureTrial(store,camera,lambda:True)
            entered=threading.Event();release=threading.Event()
            def blocking(index,deadline):entered.set();release.wait(3);return JPEG,headers(index)
            camera.hook=blocking
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(store,False,None,trial=trial))
            runtime=ServiceRuntime(server,[trial],timeout=3);result=[]
            thread=threading.Thread(target=lambda:result.append(runtime.run()));thread.start()
            try:
                self.assertTrue(runtime.ready.wait(2))
                with trial.condition:self.assertTrue(trial.condition.wait_for(lambda:trial.ready,timeout=2))
                trial.start(ID);self.assertTrue(entered.wait(2))
                runtime.request_stop();release.set();thread.join(4)
                self.assertFalse(thread.is_alive());self.assertEqual(result,[True])
                self.assertEqual(camera.calls,1);self.assertEqual(store.status()['captures'],1)
                restarted=CaptureTrial(store,camera,lambda:True);restarted.recover()
                self.assertEqual(restarted.start(ID)['state'],'cancelled')
                self.assertFalse(restarted.once());self.assertEqual(camera.calls,1)
            finally:release.set();runtime.request_stop();thread.join(4)

    def test_api_progress_cancel_auth_and_replayed_start_while_capture_is_inflight(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);camera=FakeCamera();trial=CaptureTrial(store,camera,lambda:True);trial.recover()
            class Setup:
                def status(self):return {'revision':None,'calibration':None}
            entered=threading.Event();release=threading.Event()
            def blocking(index,deadline):entered.set();release.wait(3);return JPEG,headers(index)
            camera.hook=blocking
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(store,False,None,setup=Setup(),trial=trial))
            thread=threading.Thread(target=server.serve_forever);thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            def get(route):
                with urllib.request.urlopen(base+route,timeout=2) as r:return json.load(r)
            token=get('/api/setup')['token']
            def post(data,auth=token):
                req=urllib.request.Request(base+'/api/capture-trial',data=json.dumps(data).encode(),
                    headers={'Content-Type':'application/json','X-AIEdge-Setup':auth})
                with urllib.request.urlopen(req,timeout=2) as r:return json.load(r)
            request={'action':'start','request_id':ID,'max_attempts':3,'duration_seconds':90,'interval_seconds':30}
            worker=threading.Thread(target=trial.once)
            try:
                with self.assertRaises(urllib.error.HTTPError) as denied:post(request,'wrong')
                self.assertEqual(denied.exception.code,403);denied.exception.close()
                first=post(request);worker.start();self.assertTrue(entered.wait(2))
                self.assertTrue(get('/api/capture-trial')['in_flight'])
                self.assertEqual(post(request)['job'],first['job'])
                status=get('/api/status');self.assertFalse(status['capture_enabled'])
                self.assertEqual(post({'action':'cancel','request_id':ID})['state'],'cancelling')
                release.set();worker.join(2);self.assertFalse(worker.is_alive())
                self.assertEqual(get('/api/capture-trial')['state'],'cancelled')
                self.assertEqual(camera.calls,1)
            finally:
                release.set()
                if worker.ident:worker.join(3)
                server.shutdown();thread.join();server.server_close()

    def test_actual_camera_transport_shared_trial_deadline_no_post_after_expiry(self):
        from http.server import BaseHTTPRequestHandler
        from test_camera_status import READY
        class Fixture(BaseHTTPRequestHandler):
            calls=0
            def log_message(self,*args):pass
            def do_GET(self):
                body=json.dumps(READY).encode();self.send_response(200)
                self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)))
                self.end_headers();self.wfile.write(body)
            def do_POST(self):
                Fixture.calls+=1;self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(200);self.send_header('Content-Type','image/jpeg');self.send_header('Content-Length',str(len(JPEG)))
                for key,value in headers(Fixture.calls).items():self.send_header(key,value)
                self.end_headers();self.wfile.write(JPEG)
        server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                camera=Camera(f'http://127.0.0.1:{server.server_port}');store=Store(folder)
                trial=CaptureTrial(store,camera,lambda:True);trial.recover()
                trial.start(ID,max_attempts=1,duration_seconds=2);trial.once()
                self.assertEqual(trial.status()['state'],'completed',trial.status());self.assertEqual(Fixture.calls,1)
                with self.assertRaisesRegex(ValueError,'capture_deadline_exceeded'):camera.capture(deadline=time.monotonic()-1)
                with self.assertRaisesRegex(ValueError,'capture_deadline_exceeded'):camera.readiness(deadline=time.monotonic()-1)
                self.assertEqual(Fixture.calls,1)
        finally:server.shutdown();thread.join();server.server_close()

if __name__=='__main__':unittest.main()
