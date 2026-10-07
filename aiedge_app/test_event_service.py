"""Explicit opt-in and per-event trial evidence without camera/network/model I/O."""
import copy,json,os,tempfile,unittest
from contextlib import ExitStack
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
from event_selection_config import configure
from capture_trial import CaptureTrial,decode_snapshot
from recognition import Recognition
from trial_results import build
import test_event_consumption as fixture
LIBRARY,READING=fixture.LIBRARY,fixture.READING

@unittest.skipUnless(LIBRARY and READING,'host native libraries required')
class EventServiceTests(fixture.EventConsumptionTests):
    # Use fixtures rather than inheriting their checks into this module.
    test_duplicate_partial_then_full_has_separate_cache_and_every_event_is_accounted=None
    test_selection_waits_for_durable_feedback_and_consumption_never_uses_legacy_fallback=None
    test_clock_reset_full_reanchors_preserving_unresolved_previous_segment=None
    test_bad_event_binding_cannot_advance_or_persist_accounting=None
    test_storage_failure_replays_native_state_from_durable_records_without_rerunning_inference=None
    test_event_rejection_is_accounted_before_publication_and_never_replaced_by_prior_number=None
    test_context_floor_aligns_consumer_when_captures_arrive_between_constructors=None
    test_format_change_is_withheld_before_creating_or_reinterpreting_a_segment=None
    def optin(self):
        return {'schema_version':1,'format_id':self.recognition.observation_format_id,'configuration':self.config,'capabilities':self.capabilities}
    def snapshots(self):
        with self.store.connect() as db:
            names=[row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            return {name:list(db.execute('SELECT * FROM '+name)) for name in names}
    def test_default_has_no_optin_or_storage_side_effect(self):
        legacy=Recognition(self.store,self.reader);before=self.snapshots()
        self.assertIs(configure(None,self.store,legacy,self.formats,LIBRARY),legacy);self.assertEqual(self.snapshots(),before)
    def test_explicit_configuration_preserves_references_until_construction_succeeds(self):
        path=Path(self.temp.name)/'selection.json';legacy=Recognition(self.store,self.reader);before_ref=self.formats.recognition
        value=self.optin();path.write_text(json.dumps(value))
        selected=configure(path,self.store,legacy,self.formats,LIBRARY)
        self.assertEqual(selected.observation_context,self.recognition.observation_context);self.assertIs(self.formats.recognition,before_ref);self.assertIs(selected.reader,legacy.reader)
        # Runtime selection does not start workers or construct camera/MQTT clients.
        self.assertFalse(selected.stop.is_set());self.assertEqual(self.store.status()['captures'],0)
    def test_bad_missing_duplicate_oversized_or_mismatched_config_fails_closed(self):
        path=Path(self.temp.name)/'selection.json';legacy=Recognition(self.store,self.reader)
        with self.assertRaises(ValueError):configure(path,self.store,legacy,self.formats,LIBRARY)
        for value in (None,{'schema_version':True},dict(self.optin(),format_id='b'*64),dict(self.optin(),capture_enabled=True)):
            path.write_text(json.dumps(value))
            with self.subTest(value=value),self.assertRaises(ValueError):configure(path,self.store,legacy,self.formats,LIBRARY)
        for raw in ('{"schema_version":1,"schema_version":1}','x'*32769):
            path.write_text(raw)
            with self.assertRaises(ValueError):configure(path,self.store,legacy,self.formats,LIBRARY)
        path.write_text(json.dumps(self.optin()))
        with self.assertRaises(ValueError):configure(path,self.store,legacy,self.formats,None)
    def trial(self,frames):
        trial=CaptureTrial(self.store,None,lambda:False);trial.recover();identity='a'*32
        value={'request_id':identity,'max_attempts':3,'duration_seconds':90,'interval_seconds':30,'job':'b'*32,'state':'completed',
               'started_at':self.start.isoformat(),'finished_at':self.start.isoformat(),'attempts':len(frames),'saved_frames':len(frames),
               'unique_images':len({f['sha256'] for f in frames}),'duplicate_images':len(frames)-len({f['sha256'] for f in frames}),
               'missed_slots':0,'frames':frames,'error':None,'in_flight':False,'counts_complete':True,'capture_outcome_uncertain':False,
               'context':{'pipeline_id':self.reader.pipeline_id,'format_revision':self.recognition.observation_format_id,'calibration_revision':'c'*64,'observation_context':self.recognition.observation_context},
               'training_allowed':False,'accuracy_verified':False}
        with self.store.connect() as db:db.execute('INSERT INTO capture_trials VALUES(?,?)',(identity,json.dumps(value)))
        return trial,identity,value
    def frame(self,event):
        with self.store.connect() as db:
            row=db.execute('SELECT e.camera,e.frame_id,f.captured_at,f.sha256,c.clock_id,c.monotonic_us FROM capture_events e JOIN frames f ON f.camera=e.camera AND f.frame_id=e.frame_id JOIN capture_clocks c ON c.camera=e.camera AND c.frame_id=e.frame_id WHERE e.event_id=?',(event,)).fetchone()
        return dict(zip(('camera','frame_id','captured_at','sha256','clock_id','monotonic_us'),row),event_id=event,added=True)
    def test_trial_same_image_events_keep_distinct_full_and_partial_masks(self):
        # Synthetic phases stay away from fine wrap; delta/cache assertions remain unchanged.
        self.recognize_consume(100.2);a=self.recognize_consume(100.3);self.recognize_consume(100.3);b=self.recognize_consume(100.3)
        trial,identity,value=self.trial([self.frame(a['event_id']),self.frame(b['event_id'])]);before=self.snapshots();calls=len(self.reader.calls)
        result=build(trial,self.recognition,identity)
        self.assertEqual(result['state'],'complete');self.assertEqual(result['unique_images'],1)
        self.assertEqual(result['frames'][0]['result']['observation_support']['observed'],[False,True,True])
        # Legacy full reader cache has no support field; bound request still identifies full.
        self.assertEqual(result['frames'][1]['result']['state'],'estimated')
        self.assertNotEqual(result['frames'][0]['result']['event_observation']['request_sha256'],result['frames'][1]['result']['event_observation']['request_sha256'])
        self.assertEqual(self.snapshots(),before);self.assertEqual(len(self.reader.calls),calls)
    def test_trial_schema_requires_exact_event_identity_for_selected_context(self):
        state=self.recognize_consume(100.0);trial,identity,value=self.trial([self.frame(state['event_id'])])
        for mutate in (lambda r:r['frames'][0].pop('event_id'),lambda r:r['frames'][0].update(event_id=True),lambda r:r['frames'][0].update(camera='')):
            changed=copy.deepcopy(value);mutate(changed)
            with self.assertRaisesRegex(ValueError,'trial_journal_invalid'):decode_snapshot(identity,json.dumps(changed))
    def test_trial_wrong_event_clock_is_unavailable_without_digest_fallback(self):
        state=self.recognize_consume(100.0);frame=self.frame(state['event_id']);frame['monotonic_us']+=1;trial,identity,value=self.trial([frame]);before=self.snapshots()
        with patch.object(self.recognition,'stored',side_effect=AssertionError('legacy fallback forbidden')):result=build(trial,self.recognition,identity)
        self.assertEqual(result['state'],'unavailable');self.assertEqual(result['frames'][0]['result']['error'],'trial_frame_missing');self.assertEqual(self.snapshots(),before)
    def startup(self,optin=None,requested_outputs=False,options_override=None,configuration_override=None):
        from service import run_service
        args=['service','--data',self.temp.name,'--native-library',READING,'--models','unused','--calibration-profile','synthetic','--accounting-library',LIBRARY]
        if optin is not None:args+=['--event-selection-config',str(optin)]
        options={'interval_seconds':30,'capture_enabled':requested_outputs,'mqtt_enabled':requested_outputs,'camera_url':'http://127.0.0.1' if requested_outputs else ''}
        options.update(options_override or {})
        setup=SimpleNamespace(meter=None,recognition=None,status=lambda:{'calibration':None})
        with ExitStack() as stack:
            # Startup fixture must never import or construct a real interpreter.
            stack.enter_context(patch.dict('sys.modules',{'reader':SimpleNamespace(Reader=lambda *a,**k:(_ for _ in ()).throw(AssertionError('real_reader_forbidden')))}))
            for name,value in [('sys.argv',args),('service.Store',lambda _:self.store),('service.load_options',lambda _:(options,configuration_override or {'state':'ready'})),
                               ('service.create_reader',lambda *args:self.reader),('setup_store.Setup',lambda root,factory,recognition:setup),
                               ('reading_format.FormatStore',lambda *args:self.formats)]:stack.enter_context(patch(name,value))
            server=stack.enter_context(patch('service.AppHTTPServer'));handler=stack.enter_context(patch('service.handler'))
            runtime=stack.enter_context(patch('lifecycle.ServiceRuntime'));runtime.return_value.run.return_value=True
            camera=stack.enter_context(patch('service.Camera'));mqtt=stack.enter_context(patch('mqtt_output.MqttOutput'));collector=stack.enter_context(patch('service.Collector'))
            run_service(SimpleNamespace(checkpoint=lambda:None))
            self.assertFalse(camera.called);self.assertFalse(mqtt.called);self.assertFalse(collector.called)
            return handler.call_args.args,runtime.call_args.args[1],setup
    def test_runtime_default_keeps_legacy_worker_and_no_outputs(self):
        args,workers,setup=self.startup()
        self.assertIsInstance(workers[1],Recognition);self.assertFalse(hasattr(workers[1],'observation_context'))
        self.assertEqual(args[7],{'state':'ready'});self.assertIsNotNone(workers[3]);workers[3]._drop()
    def test_supervisor_optin_wires_event_worker_without_enabling_outputs(self):
        from test_ha_event_selection import POLICY
        args,workers,setup=self.startup(options_override={'recognition_mode':'EVENT_LAST_TWO','event_selection_policy':POLICY})
        self.assertTrue(hasattr(workers[1],'observation_context'));self.assertEqual(workers[1].ha_selection['fixed_interval_seconds'],30)
        self.assertIs(setup.recognition,workers[1]);self.assertIs(self.formats.recognition,workers[1]);self.assertIsNotNone(workers[3]);workers[3]._drop()
    def test_conflicting_cli_supervisor_authority_blocks_selected_workers(self):
        from test_ha_event_selection import POLICY
        path=Path(self.temp.name)/'selection.json';path.write_text(json.dumps(self.optin()))
        args,workers,setup=self.startup(path,options_override={'recognition_mode':'EVENT_LAST_TWO','event_selection_policy':POLICY})
        self.assertEqual(args[7]['state'],'invalid');self.assertIsNone(workers[1]);self.assertIsNone(workers[3])
    def test_invalid_event_options_defaults_do_not_start_legacy_or_saved_archive(self):
        from archive import Archive
        archive=Archive(self.store)
        with archive.connect() as db:db.execute('UPDATE settings SET enabled=1,directory=?',(str(Path(self.temp.name)/'fake-nas'),))
        args,workers,setup=self.startup(configuration_override={'state':'invalid','code':'options_event_policy_invalid'})
        self.assertEqual(args[7]['code'],'options_event_policy_invalid')
        for index in (0,1,2,3,5,6):self.assertIsNone(workers[index])
        with archive.connect() as db:self.assertTrue(archive.config(db)['enabled'])
    def test_runtime_explicit_optin_wires_setup_format_and_consumer(self):
        path=Path(self.temp.name)/'selection.json';path.write_text(json.dumps(self.optin()))
        args,workers,setup=self.startup(path)
        selected=workers[1];self.assertEqual(selected.observation_context,self.recognition.observation_context)
        self.assertIs(setup.recognition,selected);self.assertIs(self.formats.recognition,selected);self.assertIs(workers[3].recognition,selected)
        self.assertEqual(args[7],{'state':'ready'});workers[3]._drop()
    def test_runtime_bad_optin_suppresses_requested_outputs_and_inference(self):
        args,workers,setup=self.startup(Path(self.temp.name)/'missing.json',requested_outputs=True)
        self.assertEqual(args[7],{'state':'invalid','code':'event_selection_configuration_invalid'})
        self.assertTrue(all(worker is None for worker in workers))
    def test_bounded_trial_records_event_ids_for_duplicate_images(self):
        from test_capture_trial import FakeCamera,Clock
        camera=FakeCamera();clock=Clock();context={'pipeline_id':self.reader.pipeline_id,'format_revision':self.recognition.observation_format_id,'observation_context':self.recognition.observation_context}
        trial=CaptureTrial(self.store,camera,lambda:True,context=lambda:context,clock=clock,wait=clock.wait);trial.recover()
        trial.start('c'*32,max_attempts=3,duration_seconds=90,interval_seconds=30);self.assertTrue(trial.once())
        snapshot=trial.status();self.assertEqual(snapshot['state'],'completed');self.assertEqual(camera.calls,3)
        frames=snapshot['frames'];self.assertEqual(len({r['event_id'] for r in frames}),3);self.assertEqual(len({r['sha256'] for r in frames}),1)
        for frame in frames:
            self.assertEqual(frame['camera'],camera.origin)
            with self.store.connect() as db:self.assertEqual(db.execute('SELECT camera,frame_id FROM capture_events WHERE event_id=?',(frame['event_id'],)).fetchone(),(camera.origin,frame['frame_id']))
        self.assertFalse(trial.once());self.assertEqual(camera.calls,3)
    def test_optin_requires_loadable_masked_accounting_before_storage_mutation(self):
        path=Path(self.temp.name)/'selection.json';path.write_text(json.dumps(self.optin()));legacy=Recognition(self.store,self.reader);before=self.snapshots()
        for library in (str(Path(self.temp.name)/'missing.dll'),READING):
            with self.subTest(library=library),self.assertRaisesRegex(ValueError,'event_selection_accounting_unavailable'):configure(path,self.store,legacy,self.formats,library)
            self.assertEqual(self.snapshots(),before)
        from accounting_native import AccountingNative
        with patch('accounting_native.AccountingNative',return_value=SimpleNamespace(supports_masked=False)),self.assertRaisesRegex(ValueError,'event_selection_accounting_unavailable'):configure(path,self.store,legacy,self.formats,LIBRARY)
        self.assertEqual(self.snapshots(),before)
    def test_runtime_accounting_store_failure_blocks_all_selected_workers(self):
        import sqlite3
        path=Path(self.temp.name)/'selection.json';path.write_text(json.dumps(self.optin()))
        with patch('consumption.Consumption',side_effect=sqlite3.DatabaseError('synthetic schema failure')):args,workers,setup=self.startup(path,requested_outputs=True)
        self.assertEqual(args[7],{'state':'invalid','code':'event_selection_accounting_unavailable'})
        self.assertTrue(all(worker is None for worker in workers));self.assertEqual(args[9],'consumption_runtime_unavailable')

if __name__=='__main__':unittest.main()
