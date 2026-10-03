"""Same-host timing evidence with generated ledgers and a loopback MQTT broker."""
import copy
import hashlib
import json
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from capture import Store, Collector
from performance import Timings, WINDOW
from recognition import Recognition
from mqtt_output import MqttOutput, broker_config
from reading_format import validate, FormatStore
from consumption import Consumption
from service import publication_state
from test_capture import JPEG, headers
from test_mqtt_output import Client, Info
from test_mqtt_transport import Broker
from test_reading_format import document
from test_recognition import Reader

class Clock:
    def __init__(self):self.value=10.
    def __call__(self):return self.value
    def advance(self,seconds):self.value+=seconds

class DeliveryTimingTests(unittest.TestCase):
    def snapshot(self,event=1,digest='b'*64):
        doc=document([1000,100]);revision=validate(doc)[1]
        return dict(format=doc,latest=dict(captured_at=datetime.now(timezone.utc).isoformat(),sha256=digest),
            reading=dict(state='estimated',value=120,source_sha256=digest,format_id=revision,unit='ft3'),
            _timing_event_id=event)
    def worker(self,directory,stats,clock):
        class DelayedInfo(Info):
            def wait_for_publish(self,timeout):clock.advance(.25)
        class DelayedClient(Client):
            fail_suffix=None
            def publish(self,topic,payload,qos,retain):
                self.sent.append((topic,payload,qos,retain))
                if self.fail_suffix and topic.endswith(self.fail_suffix):
                    return SimpleNamespace(wait_for_publish=lambda **kwargs:clock.advance(2),is_published=lambda:False)
                return DelayedInfo()
        return MqttOutput(directory,lambda:self.snapshot(),30,
            provider=lambda:broker_config(dict(host='PRIVATE-BROKER',port=1883,username='PRIVATE-USER',password='PRIVATE-PASSWORD')),
            client_factory=DelayedClient,performance=stats)
    def test_trace_bounds_identifiers_invalid_values_and_duplicate_acknowledgements(self):
        clock=Clock();stats=Timings(clock)
        for event in range(1,WINDOW+5):
            self.assertTrue(stats.admit(event,hashlib.sha256(str(event).encode()).hexdigest(),9))
        self.assertEqual(len(stats.traces),WINDOW)
        self.assertEqual(stats.snapshot()['trace_evictions_since_start'],4)
        digest=hashlib.sha256(str(WINDOW+4).encode()).hexdigest()
        self.assertFalse(stats.admit(WINDOW+4,digest,9))
        self.assertFalse(stats.publication_ack(1,hashlib.sha256(b'1').hexdigest()))
        self.assertFalse(stats.publication_ack(True,digest))
        self.assertFalse(stats.publication_ack(WINDOW+4,'c'*64))
        clock.advance(4);self.assertTrue(stats.publication_ack(WINDOW+4,digest))
        self.assertFalse(stats.publication_ack(WINDOW+4,digest))
        result=stats.snapshot()
        self.assertEqual(result['stages']['capture_request_to_broker_ack']['outcomes']['success']['median_seconds'],5)
        self.assertTrue(result['end_to_end_publication_measured'])
        encoded=json.dumps(result,allow_nan=False);self.assertNotIn(digest,encoded)
        for event,bad in ((True,'b'*64),(0,'b'*64),(1,[]),(1,'PRIVATE-IMAGE')):
            self.assertFalse(Timings(clock).admit(event,bad,9))
        for start in (True,[],float('nan'),float('inf'),-1,1000):
            other=Timings(clock);self.assertTrue(other.admit(1,'b'*64,start))
            self.assertFalse(other.publication_ack(1,'b'*64))
    def test_queue_wait_is_session_only_and_retry_does_not_reset_it(self):
        clock=Clock()
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);store.performance=Timings(clock)
            store.add('PRIVATE-CAMERA',JPEG,headers(),request_started=9)
            digest=store.status()['latest']['sha256']
            clock.advance(3)
            reader=Reader();worker=Recognition(store,reader)
            self.assertTrue(worker.once());self.assertFalse(worker.once())
            stage=store.performance.snapshot()['stages']['recognition_queue_wait']
            self.assertEqual(stage['counts_since_start']['success'],1)
            self.assertEqual(stage['outcomes']['success']['median_seconds'],3)
            store.add('PRIVATE-CAMERA',JPEG,headers('2'),request_started=clock())
            self.assertFalse(worker.once());self.assertEqual(reader.calls,1)
            restarted=Store(directory)
            self.assertFalse(restarted.performance.begin_recognition(digest))
            self.assertFalse(restarted.performance.publication_ack(1,digest))
            self.assertEqual(restarted.performance.snapshot()['state'],'not_measured')
    def test_scheduled_capture_request_correlates_after_commit_and_failure_does_not_admit(self):
        clock=Clock()
        class Camera:
            origin='PRIVATE-CAMERA'
            def readiness(self):clock.advance(2);return dict(state='ready')
            def capture(self):clock.advance(3);return JPEG,headers()
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);store.performance=Timings(clock)
            collector=Collector(store,Camera(),30);collector.once()
            event,frame=store.publication_frame();clock.advance(5)
            self.assertTrue(store.performance.publication_ack(event,frame['sha256']))
            self.assertEqual(store.performance.snapshot()['stages']['capture_request_to_broker_ack']['outcomes']['success']['median_seconds'],8)
            # A duplicate admission cannot overwrite the original capture origin.
            self.assertFalse(store.add(Camera.origin,JPEG,headers(),request_started=clock()))
            self.assertFalse(store.performance.publication_ack(event,frame['sha256']))
            before=len(store.performance.traces)
            collector.camera.capture=lambda:(_ for _ in ()).throw(ValueError('camera_timeout'))
            collector.once();self.assertEqual(len(store.performance.traces),before)
            self.assertEqual(store.status()['captures'],1)
    def test_all_three_reading_acks_required_and_retry_includes_prior_failed_delay(self):
        clock=Clock();stats=Timings(clock);stats.admit(1,'b'*64,9)
        with tempfile.TemporaryDirectory() as directory:
            worker=self.worker(directory,stats,clock)
            try:
                worker.connect(self.snapshot()['format']);worker.rediscover.clear()
                worker.client.fail_suffix='/attributes'
                with self.assertRaisesRegex(ValueError,'unconfirmed'):worker.publish_snapshot(self.snapshot())
                self.assertFalse(stats.snapshot()['end_to_end_publication_measured'])
                self.assertIsNone(worker.last_payload)
                worker.client.fail_suffix=None;worker.publish_snapshot(self.snapshot())
                report=stats.snapshot();self.assertTrue(report['end_to_end_publication_measured'])
                self.assertEqual(report['stages']['mqtt_publication']['counts_since_start']['failure'],1)
                self.assertEqual(report['stages']['mqtt_publication']['counts_since_start']['success'],1)
                elapsed=report['stages']['capture_request_to_broker_ack']['outcomes']['success']['median_seconds']
                self.assertGreaterEqual(elapsed,4)
                worker.publish_snapshot(self.snapshot())
                worker._on_message(worker.client,None,SimpleNamespace(topic='homeassistant/status',payload=b'online'))
                worker.publish_snapshot(self.snapshot())
                self.assertEqual(stats.snapshot()['stages']['capture_request_to_broker_ack']['counts_since_start']['success'],1)
                self.assertNotIn('_timing_event_id',json.dumps(worker.client.sent))
                self.assertNotIn('PRIVATE-',json.dumps(stats.snapshot()))
            finally:worker.close()
    def test_unpublishable_or_mismatched_state_never_counts_as_end_to_end(self):
        for mutation in ('ambiguous','pending','stale','hash','format','event'):
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as directory:
                clock=Clock();stats=Timings(clock);stats.admit(1,'b'*64,9)
                snapshot=self.snapshot();worker=self.worker(directory,stats,clock)
                if mutation in ('ambiguous','pending'):snapshot['reading']['state']=mutation
                if mutation=='stale':snapshot['latest']['captured_at']='2020-01-01T00:00:00Z'
                if mutation=='hash':snapshot['reading']['source_sha256']='c'*64
                if mutation=='format':snapshot['reading']['format_id']='c'*64
                if mutation=='event':snapshot['_timing_event_id']=2
                try:
                    worker.publish_snapshot(snapshot)
                    self.assertFalse(stats.snapshot()['end_to_end_publication_measured'])
                finally:worker.close()
    def test_real_paho_acknowledgements_correlate_without_exposing_internal_event(self):
        broker=Broker()
        with tempfile.TemporaryDirectory() as directory:
            stats=Timings();stats.admit(1,'b'*64,stats.clock())
            snapshot=self.snapshot()
            worker=MqttOutput(directory,lambda:snapshot,30,performance=stats,
                provider=lambda:dict(host='127.0.0.1',port=broker.port,ssl=False,username='fixture',password='test'))
            try:
                worker.publish_snapshot(snapshot)
                report=stats.snapshot();self.assertTrue(report['end_to_end_publication_measured'])
                self.assertGreater(report['stages']['capture_request_to_broker_ack']['outcomes']['success']['median_seconds'],0)
                self.assertFalse(report['ha_entity_receipt_measured'])
                self.assertNotIn('_timing_event_id',json.dumps(broker.messages))
                worker.close()
            finally:worker.close();broker.close()
        self.assertIsNone(broker.error)
    def test_private_publication_snapshot_rejects_new_event_with_identical_image(self):
        frame=dict(captured_at=datetime.now(timezone.utc).isoformat(),sha256='b'*64)
        snapshot=self.snapshot()
        recognition=SimpleNamespace(latest=lambda:{})
        formats=SimpleNamespace(evaluate=lambda _:snapshot['reading'],status=lambda:dict(revision=snapshot['reading']['format_id'],format=snapshot['format']))
        consumption=SimpleNamespace(status=lambda:dict(event_id=1,state='estimated',absolute=dict(state='estimated',value=120)))
        for sequence in ((1,2),(2,2)):
            values=iter(sequence)
            store=SimpleNamespace(publication_frame=lambda:(next(values),frame))
            result=publication_state(store,recognition,formats,consumption)
            self.assertEqual(result['reading']['state'],'pending');self.assertIsNone(result['reading']['value'])
        values=iter((1,1));store=SimpleNamespace(publication_frame=lambda:(next(values),frame))
        with patch('reading_format.reconcile_reading',side_effect=lambda r,c:r):
            self.assertEqual(publication_state(store,recognition,formats,consumption)['reading']['state'],'estimated')
        for state in ('pending','recovering','unavailable','not_configured'):
            store=SimpleNamespace(publication_frame=lambda:(1,frame))
            consumption=SimpleNamespace(status=lambda:dict(event_id=1,state=state,reason='consumption_positions_contradict_bounds'))
            result=publication_state(store,recognition,formats,consumption)
            self.assertNotEqual(result['reading']['state'],'estimated')
            self.assertIsNone(result['reading']['value'])
    def test_identical_jpeg_new_capture_can_publish_once_without_another_inference(self):
        clock=Clock()
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);store.performance=Timings(clock)
            reader=Reader();recognition=Recognition(store,reader)
            worker=self.worker(directory,store.performance,clock)
            try:
                for number in (1,2):
                    store.add('fixture',JPEG,headers(str(number)),request_started=clock())
                    recognition.once();event,frame=store.publication_frame()
                    snapshot=self.snapshot(event,frame['sha256']);snapshot['latest']=frame
                    # test_capture timestamps are fixed old data; MQTT freshness is
                    # isolated here, never used as real hardware timestamp evidence.
                    snapshot['latest']['captured_at']=(datetime.now(timezone.utc)-timedelta(seconds=3-number)).isoformat()
                    worker.publish_snapshot(snapshot)
                self.assertEqual(reader.calls,1)
                report=store.performance.snapshot()['stages']
                self.assertEqual(report['recognition_queue_wait']['counts_since_start']['success'],1)
                self.assertEqual(report['capture_request_to_broker_ack']['counts_since_start']['success'],2)
            finally:worker.close()
    @unittest.skipUnless(os.environ.get('AIEDGE_ACCOUNTING_LIBRARY'),'accounting native library required')
    def test_accounting_idle_rejected_decisions_and_failed_commit_stay_separate(self):
        from test_consumption import document as physical_document, PIPELINE
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            recognition=Recognition(store,SimpleNamespace(pipeline_id=PIPELINE,dials=[{},{}]))
            formats=FormatStore(directory,recognition);formats.save(physical_document(rate=None),None)
            ledger=Consumption(store,recognition,formats,os.environ['AIEDGE_ACCOUNTING_LIBRARY'])
            try:
                self.assertFalse(ledger.once());self.assertNotIn('accounting',store.performance.snapshot()['stages'])
                store.add('fixture',JPEG,headers())
                digest=store.status()['latest']['sha256']
                result=dict(state='rejected',pipeline_id=PIPELINE,source_sha256=digest,dial_positions=[],training_allowed=False,accuracy_verified=False)
                with store.connect() as db:db.execute('INSERT INTO inference VALUES(?,?,?,?)',(digest,PIPELINE,datetime.now(timezone.utc).isoformat(),json.dumps(result)))
                self.assertTrue(ledger.once())
                original=copy.deepcopy(ledger.status());self.assertFalse(ledger.once())
                self.assertEqual(store.performance.snapshot()['stages']['accounting']['counts_since_start']['rejected'],1)
                ledger._drop()
                ledger=Consumption(store,recognition,formats,os.environ['AIEDGE_ACCOUNTING_LIBRARY'])
                self.assertTrue(ledger.once());self.assertEqual(ledger.status(),original)
                store.add('fixture',b'\xff\xd8second\xff\xd9',headers('2',b'\xff\xd8second\xff\xd9'))
                digest=store.status()['latest']['sha256'];result['source_sha256']=digest
                with store.connect() as db:
                    db.execute('INSERT INTO inference VALUES(?,?,?,?)',(digest,PIPELINE,datetime.now(timezone.utc).isoformat(),json.dumps(result)))
                    db.execute("CREATE TRIGGER fail_accounting BEFORE INSERT ON consumption_records BEGIN SELECT RAISE(ABORT,'fixture commit failure'); END")
                with self.assertRaises(sqlite3.IntegrityError):ledger.once()
                self.assertEqual(store.performance.snapshot()['stages']['accounting']['counts_since_start']['failure'],1)
                self.assertEqual(ledger.cursor,1)
                self.assertNotEqual(ledger.status()['state'],'estimated')
                with store.connect() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM consumption_records').fetchone()[0],1)
            finally:ledger._drop()

if __name__=='__main__':unittest.main()
