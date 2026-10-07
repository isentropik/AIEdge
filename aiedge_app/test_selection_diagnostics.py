"""Diagnostic redaction is independent of operational status/error payloads."""
import json,unittest
from types import SimpleNamespace
from unittest.mock import patch
from diagnostics import build
class SelectionDiagnosticsTests(unittest.TestCase):
    def test_full_raw_error_redacted_without_losing_failure_signal(self):
        report=build(None,recognition=None)
        self.assertEqual(report['event_selection']['effective_mode'],'FULL')
        with patch('ha_event_selection.status',return_value={'requested_mode':'FULL','effective_mode':'FULL','failure':'PRIVATE-INFERENCE','private':'PRIVATE-PASSWORD'}):report=build(None)
        self.assertTrue(report['event_selection']['current_failure']);self.assertNotIn('PRIVATE-',json.dumps(report))
    def test_selected_safe_configuration_retained_private_context_policy_and_reasons_removed(self):
        raw={'requested_mode':'EVENT_LAST_TWO','effective_mode':'EVENT_LAST_TWO','state':'ready','partial_supported':True,'context_id':'a'*64,'first_event':19,'selected_indices':[5,4],'fixed_interval_seconds':30,'policy':{'PRIVATE-POLICY':'PRIVATE-VALUE'},'failure':'PRIVATE-PATH','last_decision':{'mode':'LAST_TWO','observed':[False,True,True],'reasons':['restart','PRIVATE-ERROR'],'recommended_interval_seconds':30,'private':'PRIVATE-METER','physical_scalar':'PRIVATE-READING'},'private':'PRIVATE-BROKER'}
        with patch('ha_event_selection.status',return_value=raw):report=build(None)
        s=report['event_selection'];self.assertNotIn('PRIVATE-',json.dumps(report));self.assertTrue(s['current_failure']);self.assertEqual(s['context_id'],'a'*64);self.assertEqual(s['first_event'],19);self.assertNotIn('policy',s)
        self.assertEqual(s['last_decision']['reasons'],['restart']);self.assertFalse(s['last_decision']['continuity_certified']);self.assertEqual(s['selected_indices'],[5,4])
    def test_malformed_fields_never_project_arbitrary_strings(self):
        raw={k:'PRIVATE-LEAK' for k in ('requested_mode','effective_mode','state','cadence_execution','edit_policy','partial_supported','alignment_required','timing_capability_measured','context_id','first_event','selected_indices','fixed_interval_seconds','policy')}
        raw['last_decision']={'mode':[],'observed':['PRIVATE-LEAK'],'reasons':['PRIVATE-LEAK'],'recommended_interval_seconds':'PRIVATE-LEAK'}
        with patch('ha_event_selection.status',return_value=raw):report=build(None)
        self.assertNotIn('PRIVATE-',json.dumps(report));self.assertNotIn('context_id',report['event_selection'])
    def test_safe_explicit_policy_preserved_and_status_exception_redacted(self):
        policy={'normal_interval_seconds':30,'urgent_interval_seconds':30,'full_refresh_seconds':120,'phase_probe_budget':.2,'uncertainty_probe_width':.4}
        with patch('ha_event_selection.status',return_value={'policy':policy}):self.assertEqual(build(None)['event_selection']['policy'],policy)
        with patch('ha_event_selection.status',side_effect=ValueError('PRIVATE-PATH')):
            s=build(None)['event_selection'];self.assertEqual(s,{'current_failure':True,'state':'blocked'})

    def test_new_observation_only_and_full_fallback_reasons_remain_redacted(self):
        reasons=['fine_observation_uncertain','full_refresh_uncertain','observation_only_unbounded_accounting']
        raw={'last_decision':{'mode':'LAST_TWO','reasons':reasons+['PRIVATE-CERTIFICATE'],'private':'PRIVATE-DETAIL'}}
        with patch('ha_event_selection.status',return_value=raw):value=build(None)['event_selection']['last_decision']
        self.assertEqual(value['reasons'],reasons);self.assertFalse(value['continuity_certified'])
        self.assertNotIn('PRIVATE-',json.dumps(value))
