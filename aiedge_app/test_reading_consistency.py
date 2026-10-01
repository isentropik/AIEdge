"""Joint-constraint diagnosis cannot choose a culprit or fabricate a reading."""
import copy,os,unittest
from reading_bounds import diagnose_inconsistency,feasible_ranges
from reading_format import ReadingFormat

def document(scales,errors):
    return {'version':1,'pipeline_id':'a'*64,'unit':'ft3','dials':[
        {'index':i,'value_per_revolution':p,'position_error':e}
        for i,(p,e) in enumerate(zip(scales,errors))]}


class ConsistencyTests(unittest.TestCase):
    def test_unrelated_larger_dial_is_removed_from_the_diagnostic_only(self):
        d=document([10000,1000,100],[.1,.01,.01]);positions=[1,1,5]
        original=copy.deepcopy(d)
        report=diagnose_inconsistency(d,positions)
        self.assertEqual(report['dial_indices'],[1,2]);self.assertFalse(report['individual_cause_identified'])
        self.assertFalse(report['training_allowed']);self.assertFalse(report['accuracy_verified'])
        self.assertEqual(d,original)
        self.assertEqual(feasible_ranges([10000,1000,100],positions,[.1,.01,.01])['state'],'inconsistent')

    def test_consistent_and_resource_limited_input_does_not_claim_a_conflict(self):
        for d,positions in [(document([1000,100],[.1,.1]),[1.23,2.3]),
                            (document([1e12,1e6,1],[.49]*3),[5,5,5])]:
            self.assertEqual(diagnose_inconsistency(d,positions),{'state':'not_inconsistent'})

    def test_saved_frame_group_requires_joint_constraints_not_one_bad_dial(self):
        scales=[10000000,1000000,100000,10000,1000,5]
        positions=[.2569730281829834,2.6585168838500977,5.626361846923828,
                   5.753485679626465,8.122422218322754,5.4345703125]
        d=document(scales,[.1]*6);report=diagnose_inconsistency(d,positions)
        self.assertEqual(report['dial_indices'],[1,2,3,4]);self.assertEqual(report['reduction_limited_indices'],[])
        # Every one of the four can be omitted to find a mathematical solution.
        # That is insufficient evidence to name any one of them as the cause.
        for index in report['dial_indices']:
            remaining=[i for i in range(6) if i!=index]
            self.assertEqual(feasible_ranges([scales[i] for i in remaining],
                            [positions[i] for i in remaining],[.1]*5)['state'],'bounded')

    def test_diagnostic_uses_configured_indices_instead_of_list_offsets(self):
        d=document([1000,100],[.01,.01]);d['dials'][0]['index']=4;d['dials'][1]['index']=7
        self.assertEqual(diagnose_inconsistency(d,[1,5])['dial_indices'],[4,7])

    def test_resource_limited_reduction_does_not_remove_an_unchecked_constraint(self):
        from unittest.mock import patch
        d=document([10000,1000,100],[.01]*3)
        with patch('reading_bounds.feasible_ranges',side_effect=[{'state':'inconsistent'},
                   {'state':'unavailable'},{'state':'bounded'},{'state':'bounded'}]):
            report=diagnose_inconsistency(d,[1,2,3])
        self.assertEqual(report['dial_indices'],[0,1,2]);self.assertEqual(report['reduction_limited_indices'],[0])


@unittest.skipUnless(os.environ.get('AIEDGE_READING_LIBRARY'),'reading native library required')
class IntegrationTests(unittest.TestCase):
    def test_rejected_total_stays_unavailable_to_mqtt_with_a_diagnostic(self):
        from native import Native
        from mqtt_output import fresh_state
        native=Native(os.environ['AIEDGE_READING_LIBRARY'])
        d=document([10000,1000,5],[.01,.1,.01])
        result=ReadingFormat(native,d).evaluate({'state':'estimated','pipeline_id':'a'*64,'source_sha256':'b'*64,
               'dial_positions':[{'state':'estimated','position':p} for p in [9,1,0]]})
        self.assertEqual(result['state'],'inconsistent');self.assertIsNone(result['value'])
        self.assertFalse(result['consistency']['individual_cause_identified'])
        self.assertIsNone(fresh_state({'reading':result,'latest':{'sha256':'b'*64}},90))


if __name__=='__main__':unittest.main()
