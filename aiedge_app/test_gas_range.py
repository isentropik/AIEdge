import copy,json,tempfile,unittest
from datetime import timedelta
import test_mqtt_consumption as fixtures

class LastPointTests(unittest.TestCase):
    def test_register_agreement_and_loss_of_precision(self):
        origin=fixtures.ConsumptionPublicationTests();origin.setUp()
        snapshot=origin.s
        c=snapshot['consumption']
        bands=[{'lower':820,'upper':821},{'lower':855,'upper':856}]
        bounds={'state':'bounded','wraps_register':False,'ranges':bands}
        c.update(state='ambiguous',value=None,absolute={'unit':'ft3','provenance':'temporal_consumption_bounds','bounds':bounds})
        with tempfile.TemporaryDirectory() as directory:
            w=origin.worker(directory)
            try:
                def publish():
                    w.publish_snapshot(snapshot)
                    return json.loads(next(msg[1] for msg in reversed(w.client.sent) if msg[0].endswith('/segment_range')))
                data=publish()
                self.assertEqual((data['register_ft3'],data['register_resolution_ft3'],data['event_id']),(800,100,8))
                cfg=json.loads(next(msg[1] for msg in w.client.sent if msg[0].endswith('_register_100ft3/config')))
                self.assertEqual(cfg['unit_of_measurement'],'ft³')
                self.assertNotIn('state_class',cfg)
                for updates in ({'ranges':[{'lower':899.9,'upper':900}]},
                                {'ranges':bands,'wraps_register':True},
                                {'ranges':[{'lower':-1,'upper':1}],'wraps_register':False}):
                    bounds.update(updates)
                    c['event_id']+=1;snapshot['_timing_event_id']=c['event_id']
                    data=publish()
                    self.assertNotIn('register_ft3',data)
                    self.assertIn('label',data)
                snapshot['_timing_event_id']+=1
                self.assertEqual(publish(),{})
            finally:w.close()

    def test_point_then_ambiguous_then_gap(self):
        origin=fixtures.ConsumptionPublicationTests();origin.setUp()
        s=origin.s
        s['latest']['captured_at']=s['consumption']['through_captured_at']=(origin.now-timedelta(seconds=5)).isoformat()
        with tempfile.TemporaryDirectory() as directory:
            worker=origin.worker(directory)
            try:
                worker.publish_snapshot(s)
                client=worker.client
                def latest():
                    return json.loads(next(item[1] for item in reversed(client.sent) if item[0].endswith('/segment_range')))
                point=latest()['last_acknowledged_estimate']
                self.assertEqual((point['value'],point['event_id'],point['captured_at']),(1,8,s['latest']['captured_at']))
                later=copy.deepcopy(s);c=later['consumption'];later['_timing_event_id']=9
                later['latest'].update(sha256='c'*64,captured_at=origin.now.isoformat())
                c.update(event_id=9,source_sha256='c'*64,through_captured_at=later['latest']['captured_at'],state='ambiguous',minimum=1,maximum=6.1,value=None)
                worker.publish_snapshot(later)
                self.assertEqual(latest()['last_acknowledged_estimate'],point)
                self.assertEqual(latest()['event_id'],9)
                self.assertEqual(latest()['segment_started_at'],c['anchor_captured_at'])
                self.assertNotEqual(latest()['segment_started_at'],latest()['captured_at'])
                self.assertEqual(worker.state,'waiting_for_reading')
                self.assertEqual(len([i for i in client.sent if i[0].endswith('/state')]),1)
                c['segment_id']=later['_publication_segment_id']='e'*32
                worker.publish_snapshot(later);self.assertNotIn('last_acknowledged_estimate',latest())
                worker.publish_snapshot(dict(later,consumption=None));self.assertEqual(latest(),{})
            finally:worker.close()
if __name__=='__main__':unittest.main()

