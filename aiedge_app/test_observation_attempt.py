import copy,json,unittest
from recognition import decode_result

class AttemptTests(unittest.TestCase):
    def result(self):
        return {'state':'rejected','source_sha256':'a'*64,'pipeline_id':'test-v1','accuracy_verified':False,'training_allowed':False,'dial_positions':[],
                'observation_attempt':{'schema_version':1,'source_sha256':'a'*64,'pipeline_id':'test-v1','requested_observed':[False,True]}}
    def decode(self,value):return decode_result(json.dumps(value),'a'*64,'test-v1')
    def test_rejected_partial_request_is_evidence_without_observed_positions(self):
        value=self.result();self.assertEqual(self.decode(value),value);self.assertNotIn('observation_support',value)
    def test_attempt_identity_mask_and_state_are_validated(self):
        mutations=[lambda r:r.update(state='estimated'),lambda r:r.update(observation_attempt=None),lambda r:r['observation_attempt'].update(schema_version=True),lambda r:r['observation_attempt'].update(source_sha256='b'*64),lambda r:r['observation_attempt'].update(pipeline_id='other')]
        for mask in ([],[False,False],[0,1],[True]*33,'yes',None):
            mutations.append(lambda r,mask=mask:r['observation_attempt'].update(requested_observed=mask))
        for mutate in mutations:
            value=copy.deepcopy(self.result());mutate(value)
            with self.subTest(value=value),self.assertRaises(ValueError):self.decode(value)
    def test_omitted_dial_with_conflicting_image_hash_is_rejected(self):
        value=self.result();value.pop('observation_attempt');value['state']='estimated'
        value['dial_positions']=[{'state':'unavailable','position':None,'source_sha256':'b'*64},{'state':'estimated','position':2.}]
        value['observation_support']={'schema_version':1,'source_sha256':'a'*64,'pipeline_id':'test-v1','observed':[False,True]}
        with self.assertRaisesRegex(ValueError,'dial_row_source_mismatch'):self.decode(value)

if __name__=='__main__':unittest.main()
