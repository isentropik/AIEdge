"""Synthetic opt-in contracts. No networking, original images or models."""
import copy,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from options import validate,load,InvalidOptions
from event_mode import validate_policy,final_two,edit_allowed
from event_selection import decide
from ha_event_selection import configure,status
from setup_store import Setup
from recognition import Recognition
from consumption import Consumption
import test_event_consumption as fixture
POLICY={'normal_interval_seconds':30,'urgent_interval_seconds':30,'full_refresh_seconds':120,'phase_probe_budget':.2,'uncertainty_probe_width':.4}
class PolicyTests(unittest.TestCase):
    def test_full_default_outputs_disabled(self):
        o=validate({});self.assertEqual(o['recognition_mode'],'FULL');self.assertFalse(o['capture_enabled']);self.assertFalse(o['mqtt_enabled'])
        self.assertIs(configure(o,None,'legacy',None,None),'legacy')
    def test_policy_required_explicit_and_fixed_interval(self):
        for value in ({},{**POLICY,'normal_interval_seconds':10},{**POLICY,'phase_probe_budget':True},{**POLICY,'full_refresh_seconds':float('inf')},{**POLICY,'extra':1}):
            with self.subTest(value=value),self.assertRaises(InvalidOptions):validate({'recognition_mode':'EVENT_LAST_TWO','event_selection_policy':value})
        o=validate({'recognition_mode':'EVENT_LAST_TWO','event_selection_policy':POLICY});self.assertFalse(o['capture_enabled']);self.assertFalse(o['mqtt_enabled'])
    def test_generic_physical_mapping(self):
        for count in (1,2,3,6,16):
            indices=list(reversed(range(count)));doc={'dials':[{'index':i} for i in indices]}
            self.assertEqual(final_two(doc,SimpleNamespace(dials=[{}]*count)),indices[-2:] if count>=2 else [])
        with self.assertRaises(ValueError):final_two({'dials':[{'index':1},{'index':1}]},SimpleNamespace(dials=[{},{}]))
        with self.assertRaises(ValueError):final_two({'dials':[{'index':False},{'index':1}]},SimpleNamespace(dials=[{},{}]))
    def test_generic_periods_authoritative_validated_format(self):
        from reading_format import validate as physical
        for count in (1,2,3,6,16):
            document={'version':1,'pipeline_id':'a'*64,'unit':'kWh','dials':[{'index':count-i-1,'value_per_revolution':10**(count-i),'position_error':.01} for i in range(count)]}
            normalized,_=physical(document);self.assertNotIn('maximum_rate_per_second',normalized)
            self.assertEqual(final_two(normalized,SimpleNamespace(dials=[{}]*count)),[1,0] if count>1 else [])
        document['dials'][-1]['value_per_revolution']=7
        with self.assertRaises(ValueError):physical(document)
    def test_option_duplicate_nested_and_recovery_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'options.json';blob=b'{"recognition_mode":"EVENT_LAST_TWO","event_selection_policy":{"phase_probe_budget":1,"phase_probe_budget":2}}';p.write_bytes(blob)
            options,state=load(d);self.assertEqual(state['state'],'invalid');self.assertEqual(p.read_bytes(),blob);self.assertFalse(options['capture_enabled'])
            self.assertEqual(state['code'],'options_event_policy_invalid')
    def test_setup_guard_before_reference_factory_and_persistence(self):
        setup=object.__new__(Setup);setup.recognition=SimpleNamespace(observation_context='a'*64)
        for method,args in ((setup.save,('a'*64,{},None)),(setup.add_reference,(b'invented',)),(setup.save_image_edit,('a'*64,{},None))):
            with self.assertRaisesRegex(ValueError,'restart_required'):method(*args)
        edit_allowed(SimpleNamespace())
    def test_http_selected_edits_reject_before_body_or_work(self):
        from service import handler
        H=handler(None,False,None,recognition=SimpleNamespace(observation_context='a'*64),setup=SimpleNamespace())
        closure=dict(zip(H.do_POST.__code__.co_freevars,(x.cell_contents for x in H.do_POST.__closure__)))
        for route in ('/api/setup/save','/api/setup/reference','/api/setup/image-edit','/api/setup/meter','/api/reading-format'):
            h=object.__new__(H);h.allowed=lambda:True;h.headers={'X-AIEdge-Setup':closure['token']};h.path=route;results=[]
            h.reply=lambda value,status=200:results.append((value,status))
            H.do_POST(h);self.assertEqual(results[0][1],409);self.assertEqual(results[0][0]['code'],'event_selection_restart_required')
    def test_rejected_inconsistent_bounded_full_next_decision(self):
        event={'clock_id':'fake','monotonic_us':2000000,'captured_at':'2026-10-05T00:00:02+00:00'};prior={**event,'monotonic_us':1000000,'captured_at':'2026-10-05T00:00:01+00:00'}
        doc={'dials':[{'index':i,'position_error':.01} for i in range(3)]}
        for state in ('rejected','inconsistent','bounded','ambiguous','unavailable'):
            r=decide(event,prior,{}, {'state':state},prior,False,doc,POLICY,{'partial_recognition':True,'minimum_interval_seconds':30})
            self.assertEqual(r['reader_observed'],[True]*3);self.assertFalse(r['recommendation']['alignment_bypass'])
    def test_runtime_gate_and_fixed_capability_without_cost_invention(self):
        options=validate({'recognition_mode':'EVENT_LAST_TWO','event_selection_policy':POLICY})
        doc={'dials':[{'index':i} for i in range(3)]};reader=SimpleNamespace(dials=[{}]*3,runtime=SimpleNamespace(handle=1,masked_function=lambda:None,prepare_masked=lambda:None),reuse_unchanged=True)
        recognition=SimpleNamespace(reader=reader);formats=SimpleNamespace(active=(doc,'id'))
        for supported in (True,False):
            reader.reuse_unchanged=supported
            with patch('ha_event_selection.configure_document',return_value=SimpleNamespace()) as build:
                selected=configure(options,None,recognition,formats,'host')
            caps=build.call_args.args[0]['capabilities'];self.assertEqual(caps,{'minimum_interval_seconds':30,'partial_recognition':supported});self.assertFalse(selected.ha_selection['timing_capability_measured'])
            self.assertEqual(selected.ha_selection['cadence_execution'],'fixed')
    def test_status_failure_visible_and_full_no_context(self):
        self.assertEqual(status(None)['effective_mode'],'FULL');self.assertEqual(status(SimpleNamespace(last_error='invalid'))['state'],'blocked')
    def test_rate_aliasing_never_certifies_continuity(self):
        from wheel_capture_policy import recommend
        result=recommend({'observed_phase_speed':0,'full_age_seconds':1},{'minimum_interval_seconds':30,'partial_recognition':True},POLICY)
        self.assertEqual(result['requested_mode'],'LAST_TWO');self.assertFalse(result['continuity_certified']);self.assertIsNone(result['physical_scalar'])

@unittest.skipUnless(fixture.LIBRARY and fixture.READING,'host native libraries required')
class HAMigrationTests(fixture.EventConsumptionTests):
    # Reuse invented fixtures only; parent checks are independently run once.
    for _name in list(vars(fixture.EventConsumptionTests)):
        if _name.startswith('test_'):locals()[_name]=None
    def test_full_event_full_preserves_rows_null_gaps_and_restart(self):
        self.worker._drop();legacy=Recognition(self.store,self.reader);self.formats.recognition=legacy
        self.worker=Consumption(self.store,legacy,self.formats,fixture.LIBRARY)
        for quantity in (100,100.01,100.02):
            self.event(quantity);self.assertTrue(legacy.once());self.assertTrue(self.worker.once())
        prior=self.worker.status();oldrows=self.records()
        with self.store.connect() as db:oldinference=list(db.execute('SELECT * FROM inference ORDER BY sha256,pipeline'));events=list(db.execute('SELECT * FROM capture_events'))
        self.worker._drop()
        options=validate({'recognition_mode':'EVENT_LAST_TWO','event_selection_policy':POLICY})
        selected=configure(options,self.store,legacy,self.formats,fixture.LIBRARY);self.formats.recognition=selected
        self.assertEqual(selected.observation_first_event,3)
        self.worker=Consumption(self.store,selected,self.formats,fixture.LIBRARY)
        self.assertTrue(selected.once());self.assertTrue(self.worker.once());state=self.worker.status()
        self.assertEqual(state['event_id'],3);self.assertEqual(state['prior_segment_id'],prior['segment_id']);self.assertIsNone(state['unresolved_gap']['delta'])
        self.assertTrue(set(oldrows)<=set(self.records()));calls=len(self.reader.calls);records=self.records()
        self.worker._drop();selected2=configure(options,self.store,legacy,self.formats,fixture.LIBRARY);self.formats.recognition=selected2
        self.worker=Consumption(self.store,selected2,self.formats,fixture.LIBRARY)
        while self.worker.once():pass
        self.assertFalse(selected2.once());self.assertEqual(self.worker.status(),state);self.assertEqual(self.records(),records);self.assertEqual(len(self.reader.calls),calls)
        self.worker._drop();self.formats.recognition=legacy;self.worker=Consumption(self.store,legacy,self.formats,fixture.LIBRARY)
        self.assertTrue(self.worker.once());back=self.worker.status();self.assertEqual(back['prior_segment_id'],state['segment_id']);self.assertIsNone(back['unresolved_gap']['delta'])
        with self.store.connect() as db:
            self.assertEqual(list(db.execute('SELECT * FROM inference ORDER BY sha256,pipeline')),oldinference);self.assertEqual(list(db.execute('SELECT * FROM capture_events')),events)
    def test_missing_native_export_closed_profile_and_reuse_disabled_only_full(self):
        self.worker._drop();legacy=Recognition(self.store,self.reader)
        options=validate({'recognition_mode':'EVENT_LAST_TWO','event_selection_policy':POLICY})
        for field in ('masked_function','handle','reuse_unchanged','runtime'):
            reader=copy.copy(self.reader);reader.runtime=copy.copy(self.reader.runtime);reader.calls=[]
            if field in ('masked_function','handle'):setattr(reader.runtime,field,None)
            else:setattr(reader,field,False if field=='reuse_unchanged' else None)
            legacy=Recognition(self.store,reader)
            selected=configure(options,self.store,legacy,self.formats,fixture.LIBRARY)
            self.assertFalse(selected.capabilities['partial_recognition']);self.event(100+self.counter)
            self.formats.recognition=selected;self.worker=Consumption(self.store,selected,self.formats,fixture.LIBRARY)
            while selected.once():
                while self.worker.once():pass
            self.assertTrue(reader.calls);self.assertTrue(all(all(mask) for _,mask in reader.calls));self.worker._drop()
