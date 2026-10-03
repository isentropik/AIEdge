"""Integrated publisher checks with the existing acknowledged client fixture."""
import copy,json,unittest
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
import test_mqtt_output as fixtures
from reading_format import validate


class SemanticDedupTests(unittest.TestCase):
    setUp=fixtures.MqttTests.setUp
    tearDown=fixtures.MqttTests.tearDown

    def start(self):
        self.now=100.
        self.worker.clock=lambda:self.now
        self.worker.publish_snapshot(self.snapshot)
        self.client=self.clients[-1]
        return len(self.client.sent)

    def new_frame(self,digest='c'*64):
        self.snapshot['latest']={'captured_at':datetime.now(timezone.utc).isoformat(),'sha256':digest}
        self.snapshot['reading']['source_sha256']=digest

    def states(self):
        return [json.loads(row[1]) for row in self.client.sent if row[0].endswith('/state')]

    def test_same_number_new_frame_suppresses_every_reading_message(self):
        count=self.start();self.new_frame();self.now+=30
        self.assertEqual(self.worker._publish_snapshot(self.snapshot),'duplicate')
        self.assertEqual(len(self.client.sent),count)
        self.assertEqual(self.states()[-1]['source_sha256'],'b'*64)

    def test_tiny_numeric_change_is_not_rounded_away(self):
        self.start();self.new_frame();self.snapshot['reading']['value']=120.000001
        self.worker.publish_snapshot(self.snapshot)
        self.assertEqual(len(self.states()),2)
        self.assertEqual(self.states()[-1]['value'],120.000001)

    def test_receiver_expiry_refresh_uses_latest_evidence(self):
        self.start();self.new_frame();self.now+=59.999
        self.worker.publish_snapshot(self.snapshot);self.assertEqual(len(self.states()),1)
        self.now+=.001;self.worker.publish_snapshot(self.snapshot)
        self.assertEqual(len(self.states()),2)
        self.assertEqual(self.states()[-1]['source_sha256'],'c'*64)
        self.assertEqual(self.worker.config['expire_after'],90)

    def test_expiry_refresh_rejects_stale_reading(self):
        self.start();self.now+=60
        self.snapshot['latest']['captured_at']=(datetime.now(timezone.utc)-timedelta(seconds=100)).isoformat()
        self.worker.publish_snapshot(self.snapshot)
        self.assertEqual(len(self.states()),1);self.assertEqual(self.client.sent[-1][1],'offline')

    def test_invalid_then_equal_value_recovery_republishes(self):
        self.start();self.snapshot['reading']['state']='ambiguous'
        self.worker.publish_snapshot(self.snapshot);self.assertEqual(self.client.sent[-1][1],'offline')
        count=len(self.client.sent);self.worker.publish_snapshot(self.snapshot)
        self.assertEqual(len(self.client.sent),count)
        self.snapshot['reading']['state']='estimated';self.new_frame()
        self.worker.publish_snapshot(self.snapshot);self.assertEqual(len(self.states()),2)

    def test_same_value_pipeline_change_forces_republication(self):
        self.start()
        self.snapshot['format']=copy.deepcopy(self.doc)
        self.snapshot['format']['pipeline_id']='d'*64
        self.snapshot['reading']['format_id']=validate(self.snapshot['format'])[1]
        self.worker.publish_snapshot(self.snapshot)
        self.assertEqual(len(self.states()),2);self.assertEqual(len(self.clients),1)

    def test_same_value_segment_change_forces_republication(self):
        self.snapshot['_publication_segment_id']='old';self.start()
        self.snapshot['_publication_segment_id']='new'
        self.worker.publish_snapshot(self.snapshot);self.assertEqual(len(self.states()),2)
        self.assertNotIn('_publication_segment_id',self.client.sent[-3][1])

    def test_rediscovery_forces_equal_value_through(self):
        self.start();self.new_frame()
        self.worker._on_message(self.client,None,SimpleNamespace(topic='homeassistant/status',payload=b'online'))
        self.worker.publish_snapshot(self.snapshot)
        self.assertEqual(len(self.states()),2)

    def test_reconnect_forces_equal_value_through(self):
        self.start();self.worker.close();self.new_frame()
        self.worker.publish_snapshot(self.snapshot);self.assertEqual(len(self.clients),2)
        self.assertTrue(any(row[0].endswith('/state') for row in self.clients[-1].sent))

    def test_partial_ack_after_prior_success_does_not_suppress_retry(self):
        for suffix in ('/state','/attributes','/availability'):
            with self.subTest(suffix=suffix):
                self.worker.rediscover.set();self.start()
                original=self.client.publish
                def fail(topic,payload,qos,retain):
                    if topic.endswith(suffix):
                        return SimpleNamespace(wait_for_publish=lambda **kw:None,is_published=lambda:False)
                    return original(topic,payload,qos,retain)
                self.client.publish=fail;self.new_frame();self.snapshot['reading']['value']+=1
                with self.assertRaisesRegex(ValueError,'unconfirmed'):
                    self.worker.publish_snapshot(self.snapshot)
                self.assertIsNone(self.worker.last_key);self.assertIsNone(self.worker.last_payload)
                self.client.publish=original
                self.worker.publish_snapshot(self.snapshot)
                self.assertEqual(self.states()[-1]['value'],self.snapshot['reading']['value'])

    def test_clock_reset_forces_republication(self):
        self.start();self.now=0
        self.worker.publish_snapshot(self.snapshot);self.assertEqual(len(self.states()),2)

    def test_invalid_clock_does_not_publish_number(self):
        self.start();self.now=float('nan');count=len(self.client.sent)
        with self.assertRaisesRegex(ValueError,'invalid_publication_clock'):
            self.worker.publish_snapshot(self.snapshot)
        self.assertEqual(len(self.client.sent),count)

    def test_missing_format_offline_then_same_reading_recovers(self):
        self.start();self.snapshot['format']=None
        self.worker.publish_snapshot(self.snapshot);self.assertEqual(self.client.sent[-1][1],'offline')
        self.snapshot['format']=self.doc;self.worker.publish_snapshot(self.snapshot)
        self.assertEqual(len(self.states()),2)

    def test_suppressed_frame_has_no_invented_publication_ack(self):
        self.start();self.new_frame();self.snapshot['_timing_event_id']=2
        acks=[];self.worker.performance.publication_ack=lambda *args:acks.append(args)
        self.worker.publish_snapshot(self.snapshot);self.assertEqual(acks,[])
        self.now+=60;self.worker.publish_snapshot(self.snapshot)
        self.assertEqual(acks,[(2,'c'*64)])


if __name__=='__main__':unittest.main()
