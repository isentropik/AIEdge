import json
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import test_mqtt_consumption as fixtures
from overview_history import OverviewHistory


class OverviewTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.directory = Path(root.name)
        self.fixture = fixtures.ConsumptionPublicationTests()
        self.fixture.setUp()
        self.output = self.fixture.worker(root.name)
        self.addCleanup(self.output.close)

    def publish(self):
        self.output.publish_snapshot(self.fixture.s)
        return self.output.status()['usage']['historical']

    def test_positive_ack_survives_restart_and_keeps_gap(self):
        point = self.publish()
        self.assertEqual(point['event_id'], self.fixture.s['_timing_event_id'])
        self.assertEqual(point['segment_started_at'], self.fixture.s['consumption']['anchor_captured_at'])
        self.assertEqual(point, OverviewHistory(self.directory, self.output.identity).point)
        self.assertIsNone(self.fixture.s['consumption']['unresolved_gap']['delta'])
        self.assertIsNone(OverviewHistory(self.directory, 'other').point)

    def test_unacknowledged_or_zero_does_not_replace_history(self):
        point = self.publish()
        history = self.output.overview_history
        history.acknowledge(dict(point, value=0, event_id=point['event_id']+1))
        history.acknowledge(dict(point, source_sha256='c'*64))
        history.acknowledge(dict(point, event_id=point['event_id']-1))
        self.assertEqual(point, history.point)
        self.output.last_key = None
        with patch.object(self.output, '_publish', side_effect=ValueError('mqtt_publish_unconfirmed')), self.assertRaises(ValueError):
            self.output.publish_snapshot(self.fixture.s)
        self.assertEqual(point, history.point)

    def test_last_published_nominals_survive_disconnect_and_keep_source(self):
        self.publish()
        scope = self.output.overview_format
        values = {'value_ft3':'12345.123456789012', 'event_id':18, 'measured_at':'2026-01-01T01:00:00+00:00'}
        self.output.overview_absolute = (scope, values)
        self.output.overview_daily = (scope, dict(values, value_ft3='0.00'))
        self.output.connected.clear()
        state = self.output.status()
        self.assertFalse(state['overview_connected'])
        self.assertEqual(values, state['usage']['absolute_nominal'])
        self.assertEqual(state['usage']['daily_nominal']['event_id'],18)
        self.output.overview_format = 'another format'
        self.assertFalse(self.output.status()['usage'])

    def test_disk_error_does_not_interrupt_publication(self):
        with patch('overview_history.Setup._atomic',side_effect=OSError('full')):
            self.output.connect(self.fixture.s['format'])
            point = self.publish()
        self.assertEqual(self.output.state, 'publishing')
        self.assertTrue(self.output.overview_history.save_failed)
        self.output.overview_history.acknowledge(point)
        self.assertFalse(self.output.overview_history.save_failed)

    def test_invalid_checkpoint_has_no_value(self):
        history = self.output.overview_history
        for contents in (b'broken', json.dumps({'instance':self.output.identity,'point':{'value':10}}).encode()):
            history.path.write_bytes(contents)
            self.assertIsNone(OverviewHistory(self.directory,self.output.identity).point)

    def test_existing_retained_estimate_is_read_only_and_meter_scoped(self):
        point = self.publish()
        topic = self.output.history_topic
        client = self.output.client
        self.assertIn(((topic,), {'qos':1}), client.subscriptions)
        self.assertFalse(any(msg[0] == topic for msg in client.sent))
        self.output.overview_history.point = None
        payload = json.dumps(point).encode()
        def receive(t, data):
            self.output._on_message(client, None, SimpleNamespace(topic=t, payload=data))
        receive(topic + '-other', payload)
        receive(topic, b'bad')
        self.assertNotIn('historical', self.output.status()['usage'])
        receive(topic, payload)
        self.assertEqual(self.output.status()['usage']['historical'], point)
        receive(topic, json.dumps(dict(point,event_id=point['event_id']-1)).encode())
        self.assertEqual(self.output.status()['usage']['historical'], point)
        self.output.overview_format = 'different'
        self.assertNotIn('historical', self.output.status()['usage'])
