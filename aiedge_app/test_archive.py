"""Archive isolation, provenance and restart tests; no real NAS or camera writes."""
import copy, hashlib, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
from capture import Store
from archive import Archive, ArchiveConflict
from archive_copy import ArchiveError, canonical, copy as copy_image, validate_request, mounted_target, MountedFilesystem
from test_capture import JPEG, headers


class LocalFilesystem:
    """Filesystem substitute for protocol checks, not a network-mount claim."""
    def __init__(self, root): self.root = Path(root)
    def directory(self, parent, name, create=True):
        value = parent/name
        if create: value.mkdir(exist_ok=True)
        if not value.is_dir(): raise FileNotFoundError()
        return value
    def read(self, parent, name, limit):
        value = (parent/name).read_bytes()
        if len(value)>limit: raise ArchiveError('archive_conflict')
        return value
    def write(self, parent, name, body):
        with (parent/name).open('xb') as stream: stream.write(body)
    def names(self, parent): return {p.name for p in parent.iterdir()}
    def sync(self, parent): pass
    def promote(self, parent, temporary, final): os.rename(parent/temporary, parent/final)
    def close(self, value): pass


class Process:
    def __init__(self, code=None, exits_on_kill=True): self.returncode=code; self.killed=0; self.exits_on_kill=exits_on_kill
    def poll(self): return self.returncode
    def kill(self):
        self.killed+=1
        if self.exits_on_kill: self.returncode=-9
    def wait(self, timeout=None):
        if self.returncode is None: raise subprocess.TimeoutExpired('archive-fixture',timeout)
        return self.returncode


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.store=Store(self.root/'data');self.store.add('http://fixture.invalid',JPEG,headers())
        self.calls=[];self.proc=Process()
        def launch(request,result): self.calls.append((json.loads(request.read_bytes()),result));return self.proc
        self.worker=Archive(self.store,deadline=.02,launcher=launch)
    def tearDown(self): self.temp.cleanup()
    def enable(self,directory='/media/fixture'):
        return self.worker.save({'enabled':True,'directory':directory},self.worker.status()['revision'])
    def complete(self,result=None):
        request,output=self.calls[-1]
        output.write_bytes(canonical(result or {'state':'copied','manifest_sha256':hashlib.sha256(canonical(request['metadata'])).hexdigest()}))
        self.proc.returncode=0;self.worker.tick()
    def test_default_off_never_spawns_or_touches_destination(self):
        with patch('archive.Path.resolve',side_effect=AssertionError('must not resolve a NAS path')):
            self.worker.tick();state=self.worker.status()
        self.assertEqual(state['state'],'disabled');self.assertFalse(self.calls);self.assertEqual(self.store.status()['captures'],1)
    def test_choices_and_optimistic_conflict(self):
        old=self.worker.status()['revision'];self.enable()
        with self.assertRaises(ArchiveConflict):self.worker.save({'enabled':False,'directory':''},old)
        for path in ('\\\\server\\share','/media','/media/a/../b','/media/a//b','/media/a/./b','/media/a/','/media/a\\b'):
            with self.subTest(path=path),self.assertRaises(ValueError):self.enable(path)
        with self.assertRaises(ValueError):self.worker.save({'enabled':1,'directory':'/media/a'},self.worker.status()['revision'])
    def test_capture_provenance_is_exact_and_contains_no_estimates(self):
        self.enable();request=self.worker.next_request();metadata=request['metadata']
        with self.store.connect() as db:source=db.execute('SELECT frame_id,captured_at,received_at,sha256,bytes FROM frames').fetchone()
        self.assertEqual([metadata[k] for k in ('frame_id','captured_at','received_at','image_sha256','image_bytes')],list(source))
        self.assertEqual(metadata['camera_key'],hashlib.sha256(b'http://fixture.invalid').hexdigest())
        self.assertIsNone(metadata['clock_id']);self.assertIsNone(metadata['monotonic_us'])
        self.assertFalse(metadata['training_allowed']);self.assertFalse(metadata['accuracy_verified']);self.assertEqual(metadata['split_status'],'unchecked')
        self.assertNotIn('fixture.invalid',json.dumps(metadata));self.assertNotIn('value',metadata)
    def test_exact_acknowledgement_and_duplicate_capture_events(self):
        self.store.add('http://fixture.invalid',JPEG,headers('2'));self.enable();self.worker.tick();self.complete()
        self.assertEqual(self.worker.status()['copied_events'],1);self.assertEqual(self.worker.status()['pending_events'],1)
        self.proc=Process();self.worker.tick();self.complete();self.assertEqual(self.worker.status()['state'],'ready')
        self.assertEqual([request['metadata']['event_id'] for request,_ in self.calls],[1,2]);self.assertEqual(self.store.status()['unique_images'],1)
    def test_restart_resumes_acknowledged_cursor_and_preserves_instance(self):
        self.enable();self.worker.tick();self.complete();self.store.add('http://fixture.invalid',JPEG,headers('2'))
        restored=Archive(self.store);self.assertEqual(restored.instance,self.worker.instance)
        request=restored.next_request();self.assertEqual(request['metadata']['event_id'],2)
    def test_lost_result_retries_same_manifest_after_restart(self):
        self.enable();request=self.worker.next_request();restored=Archive(self.store)
        self.assertEqual(restored.next_request(),request);self.assertEqual(restored.status()['copied_events'],0)
    def test_bad_ack_does_not_advance_cursor_or_leak_error_text(self):
        self.enable();self.worker.tick();self.complete({'state':'copied','manifest_sha256':'0'*64,'password':'private-fixture'})
        state=self.worker.status();self.assertEqual(state['copied_events'],0);self.assertEqual(state['error'],'archive_worker_failed')
        self.assertNotIn('private-fixture',json.dumps(state));self.worker.tick();self.assertEqual(len(self.calls),1)
    def test_permanent_conflict_requires_retry_and_keeps_original(self):
        original=self.store.image(hashlib.sha256(JPEG).hexdigest());self.enable();self.worker.tick();self.complete({'state':'error','code':'archive_conflict'})
        self.assertEqual(self.worker.status()['state'],'blocked');self.worker.tick();self.assertEqual(len(self.calls),1)
        self.worker.retry(self.worker.status()['revision']);self.proc=Process();self.worker.tick();self.assertEqual(len(self.calls),2)
        self.assertEqual(self.store.image(hashlib.sha256(JPEG).hexdigest()),original)
    def test_stalled_child_is_single_slot_and_does_not_block_capture_or_status(self):
        self.proc=Process(exits_on_kill=False);self.enable();self.worker.tick();self.worker.active['deadline']=0;self.worker.tick()
        for _ in range(5):self.worker.tick()
        started=time.monotonic();self.store.add('http://fixture.invalid',JPEG,headers('2'));state=self.worker.status()
        self.assertLess(time.monotonic()-started,1);self.assertEqual(self.proc.killed,1);self.assertEqual(len(self.calls),1)
        self.assertEqual(state['state'],'waiting_for_worker');self.assertEqual(state['error'],'archive_timeout');self.assertEqual(state['copied_events'],0)
    def test_timeout_cannot_accept_late_success(self):
        self.enable();self.worker.tick();self.worker.active['deadline']=0;self.worker.tick();self.complete()
        self.assertEqual(self.worker.status()['copied_events'],0);self.assertEqual(self.worker.status()['error'],'archive_timeout')
    def test_disable_finishes_only_current_copy(self):
        self.enable();self.worker.tick();self.worker.save({'enabled':False,'directory':'/media/fixture'},self.worker.status()['revision'])
        self.complete();self.worker.tick();self.assertEqual(len(self.calls),1);self.assertEqual(self.worker.status()['state'],'disabled')
        self.assertEqual(self.worker.status()['copied_events'],1)
    def test_destination_change_does_not_credit_old_copy_to_new_destination(self):
        self.enable();self.worker.tick();self.enable('/media/other');self.complete()
        self.assertEqual(self.worker.status()['copied_events'],0);self.proc=Process();self.worker.tick()
        self.assertEqual(self.calls[-1][0]['directory'],'/media/other')
    def test_corrupt_source_metadata_blocks_without_spawning(self):
        with self.store.connect() as db:db.execute('UPDATE frames SET bytes=-1')
        self.enable();self.worker.tick();self.assertFalse(self.calls);self.assertEqual(self.worker.status()['error'],'archive_source_invalid')
    def test_real_child_deadline_and_worker_shutdown(self):
        def sleeper(request,result):return subprocess.Popen([sys.executable,'-c','import time;time.sleep(10)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}))
        self.worker.launcher=sleeper;self.enable();self.worker.tick();proc=self.worker.active['process']
        try:
            self.worker.active['deadline']=0;self.worker.tick();proc.wait(timeout=2);self.worker.tick()
            self.assertEqual(self.worker.status()['error'],'archive_timeout');self.assertEqual(self.worker.status()['copied_events'],0)
        finally:
            if proc.poll() is None:proc.kill();proc.wait(timeout=2)
    def test_stop_kills_child_and_keeps_durable_unacknowledged_intent(self):
        self.enable();self.worker.tick();self.worker.stop.set();self.worker.run()
        self.assertEqual(self.proc.killed,1);self.assertEqual(self.worker.status()['copied_events'],0)
        with self.worker.connect() as db:self.assertEqual(db.execute('SELECT inflight FROM targets').fetchone()[0],1)
    def test_child_environment_contains_no_supervisor_or_camera_secret(self):
        with patch.dict(os.environ,{'SUPERVISOR_TOKEN':'private-fixture','CAMERA_PASSWORD':'private-fixture'}),patch('archive.subprocess.Popen',return_value=Process()) as popen:
            self.worker.launch(self.root/'request',self.root/'result')
        env=popen.call_args.kwargs['env'];self.assertNotIn('SUPERVISOR_TOKEN',env);self.assertNotIn('CAMERA_PASSWORD',env)


class ArchiveCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.store=Store(self.root/'data');self.store.add('fixture',JPEG,headers())
        self.worker=Archive(self.store);self.worker.save({'enabled':True,'directory':'/media/test'},self.worker.status()['revision']);self.request=self.worker.next_request()
        self.target=self.root/'target';self.target.mkdir();self.fs=lambda directory:LocalFilesystem(self.target)
    def tearDown(self):self.temp.cleanup()
    def test_idempotent_jpeg_and_distinct_capture_manifests(self):
        first=copy_image(self.request,self.fs);self.assertEqual(copy_image(self.request,self.fs),first)
        another=copy.deepcopy(self.request);another['metadata']['event_id']=2;another['metadata']['frame_id']='2';copy_image(another,self.fs)
        base=self.target/'aiedge'/self.worker.instance
        self.assertEqual(len(list((base/'objects').iterdir())),1);self.assertEqual(len(list((base/'events').iterdir())),2)
    def test_remote_conflict_keeps_remote_and_local_bytes(self):
        copy_image(self.request,self.fs);target=next((self.target/'aiedge'/self.worker.instance/'objects').iterdir())/'image.jpg';target.write_bytes(b'conflict')
        with self.assertRaisesRegex(ArchiveError,'archive_conflict'):copy_image(self.request,self.fs)
        self.assertEqual(target.read_bytes(),b'conflict');self.assertEqual(Path(self.request['source']).read_bytes(),JPEG)
    def test_corrupt_source_never_opens_destination(self):
        Path(self.request['source']).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ArchiveError,'archive_source_invalid'):copy_image(self.request,lambda _:self.fail('destination opened'))
    def test_rejects_forged_training_timestamps_clocks_and_schema(self):
        variants=[('schema_version',True),('event_id',True),('training_allowed',True),('accuracy_verified',True),('frame_id','../a'),('captured_at','2026-10-01'),('received_at',[]),('clock_id','clock'),('monotonic_us',10)]
        for key,value in variants:
            request=copy.deepcopy(self.request);request['metadata'][key]=value
            with self.subTest(key=key),self.assertRaises(ArchiveError):validate_request(request)
    def test_mount_admission_requires_deepest_network_mount(self):
        table='1 0 0:1 / / rw - ext4 /dev/root rw\n2 1 0:2 / /media/test rw - cifs //fixture/share rw\n'
        self.assertEqual(mounted_target('/media/test/folder',table),('/media/test',(0,2),('folder',)))
        for suffix in ('3 2 0:3 / /media/test/folder rw - tmpfs tmpfs rw\n','3 2 0:3 / /media/test/folder rw - ext4 /dev/local rw\n'):
            with self.assertRaisesRegex(ArchiveError,'archive_mount_unavailable'):mounted_target('/media/test/folder',table+suffix)
        with self.assertRaises(ArchiveError):mounted_target('/media/test',table.splitlines()[0])
    def test_mountinfo_escaped_spaces_and_protocols(self):
        for protocol in ('cifs','smb3','nfs','nfs4'):
            table=f'1 0 0:1 / /media/a\\040b rw - {protocol} fixture rw'
            self.assertEqual(mounted_target('/media/a b/child',table)[0],'/media/a b')
    def test_interrupted_staging_is_resumed_without_new_orphans(self):
        class Interrupted(LocalFilesystem):
            def write(inner,parent,name,body):
                if name=='object.json':raise OSError('fixture disconnect')
                super(Interrupted,inner).write(parent,name,body)
        for _ in range(2):
            with self.assertRaises(OSError):copy_image(self.request,lambda _:Interrupted(self.target))
        objects=self.target/'aiedge'/self.worker.instance/'objects'
        self.assertEqual(len(list(objects.iterdir())),1)
        copy_image(self.request,self.fs)
        self.assertEqual([p.name for p in objects.iterdir()],[self.request['metadata']['image_sha256']])


@unittest.skipUnless(sys.platform=='linux','Linux mount and process isolation checks')
class ArchiveLinuxTests(unittest.TestCase):
    def test_nofollow_directory_files_and_nonregular_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);fs=MountedFilesystem.__new__(MountedFilesystem);fs.root=os.open(root,os.O_RDONLY|os.O_DIRECTORY);fs.device=os.fstat(fs.root).st_dev
            try:
                (root/'outside').mkdir();(root/'link').symlink_to(root/'outside',target_is_directory=True)
                with self.assertRaises(OSError):fs.directory(fs.root,'link')
                (root/'data').write_bytes(b'original');(root/'filelink').symlink_to(root/'data')
                with self.assertRaises(OSError):fs.read(fs.root,'filelink',100)
                os.mkfifo(root/'fifo')
                with self.assertRaises(ArchiveError):fs.read(fs.root,'fifo',100)
                self.assertEqual((root/'data').read_bytes(),b'original')
            finally:os.close(fs.root)
    def test_child_lock_admits_one_process_and_parent_death_stops_it(self):
        # A subprocess acquires the actual local guard, then stalls without NAS I/O.
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);guard=str(root/'lock');ready=root/'ready'
            script="import os,sys,time;from pathlib import Path;from archive_copy import child_guard;fd=child_guard(sys.argv[1],int(sys.argv[2]));Path(sys.argv[3]).write_text('ready');time.sleep(10)"
            child=subprocess.Popen([sys.executable,'-c',script,guard,str(os.getpid()),str(ready)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                deadline=time.monotonic()+2
                while not ready.exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(ready.exists())
                # Use another child so prctl cannot alter this test runner's signal policy.
                second=subprocess.run([sys.executable,'-c',"import sys;from archive_copy import child_guard,ArchiveError;\ntry: child_guard(sys.argv[1],int(sys.argv[2]))\nexcept ArchiveError as e: print(str(e))",guard,str(os.getpid())],capture_output=True,text=True,timeout=2)
                self.assertEqual(second.stdout.strip(),'archive_worker_busy')
            finally:child.kill();child.wait(timeout=2)
        # Now kill an intermediate parent and verify the guarded child stops.
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);ready=root/'ready';pidfile=root/'pid'
            parent_script="import os,subprocess,sys,time;from pathlib import Path;code=\"import os,sys,time;from pathlib import Path;from archive_copy import child_guard;fd=child_guard(sys.argv[1],int(sys.argv[2]));Path(sys.argv[3]).write_text('ready');time.sleep(20)\";child=subprocess.Popen([sys.executable,'-c',code,sys.argv[1],str(os.getpid()),sys.argv[2]]);Path(sys.argv[3]).write_text(str(child.pid));time.sleep(20)"
            parent=subprocess.Popen([sys.executable,'-c',parent_script,str(root/'lock'),str(ready),str(pidfile)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            child_pid=None
            try:
                deadline=time.monotonic()+3
                while not ready.exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(ready.exists());child_pid=int(pidfile.read_text());parent.kill();parent.wait(timeout=2)
                deadline=time.monotonic()+3;stopped=False
                while time.monotonic()<deadline:
                    try:stopped=Path(f'/proc/{child_pid}/stat').read_text().split(') ',1)[1].split()[0]=='Z'
                    except FileNotFoundError:stopped=True
                    if stopped:break
                    time.sleep(.01)
                self.assertTrue(stopped,'guarded child survived parent death')
            finally:
                if parent.poll() is None:parent.kill();parent.wait(timeout=2)
                if child_pid:
                    try:os.kill(child_pid,9)
                    except ProcessLookupError:pass


if __name__=='__main__':unittest.main()
