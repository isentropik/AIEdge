import copy,json,tempfile,unittest
from datetime import timedelta
import test_mqtt_consumption as fixtures

class LastPointTests(unittest.TestCase):
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
                self.assertEqual(worker.state,'waiting_for_reading')
                self.assertEqual(len([i for i in client.sent if i[0].endswith('/state')]),1)
                c['segment_id']=later['_publication_segment_id']='e'*32
                worker.publish_snapshot(later);self.assertNotIn('last_acknowledged_estimate',latest())
                worker.publish_snapshot(dict(later,consumption=None));self.assertEqual(latest(),{})
            finally:worker.close()
if __name__=='__main__':unittest.main()

