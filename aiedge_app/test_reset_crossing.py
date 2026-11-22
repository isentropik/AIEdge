"""Connection resets, wrapped dials and expired charts. All captures are synthetic."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import URLError

import capture_recovery as recovery
from capture import Camera as Transport, Collector, Store
from daily_mqtt import DailyPublisher, _source_digest
from dial_travel import advance_band, tail_edges
from test_capture_continuation import Camera, configure, request
import test_daily_turn_recovery as turn_fixtures
import test_transfer_recovery as body_fixtures


class ResetTests(unittest.TestCase):
    def test_direct_and_wrapped_reset_before_headers(self):
        for error in (ConnectionResetError(), URLError(ConnectionResetError())):
            with self.subTest(error=error):
                camera = Transport('http://127.0.0.1')
                with patch.object(camera.opener,'open',side_effect=error) as opened:
                    with self.assertRaisesRegex(recovery.RequestTimeout,'camera_connection_reset'):
                        camera.capture()
                self.assertEqual(opened.call_count,1)

    def test_partial_body_reset_requires_valid_provenance(self):
        for complete in (True,False):
            camera=Transport('http://127.0.0.1')
            response=body_fixtures.BodyTimeoutTransportTests().response()
            if not complete:
                del response.headers['X-AIEdge-SHA256']
            with patch.object(response,'read1',side_effect=[b'123',ConnectionResetError()]), patch.object(camera.opener,'open',return_value=response) as opened:
                with self.assertRaisesRegex(ValueError,'camera_connection_reset') as error:
                    camera.capture()
            self.assertEqual(opened.call_count,1)
            self.assertTrue(response.closed)
            self.assertEqual(isinstance(error.exception,recovery.BodyTimeout),complete)
            if complete:
                self.assertEqual(error.exception.evidence['received_bytes'],3)

    def test_typed_reset_survives_restart_and_accepts_once_without_duplicate_post(self):
        for error in (recovery.RequestTimeout(reset=True),recovery.BodyTimeout(body_fixtures.EVIDENCE,reset=True)):
            with self.subTest(stage=error.evidence['stage']),TemporaryDirectory() as tmp:
                store=Store(tmp)
                camera=Camera([True,error,True])
                worker=configure(Collector(store,camera,6))
                worker.once()
                worker.once()
                restored=configure(Collector(Store(tmp),camera,6))
                camera.ready['state']='busy'
                restored.once()
                self.assertEqual(camera.calls,2)
                camera.ready['state']='ready'
                restored.once()
                self.assertEqual(camera.calls,2)
                restored.once()
                self.assertEqual(camera.calls,3)
                with store.connect() as db:
                    self.assertEqual(db.execute('select outcome,event_id,error from continuous_capture_outcomes order by rowid').fetchall(),
                                     [('committed',1,None),('unknown',None,'camera_connection_reset'),('committed',2,None)])
                    self.assertEqual(db.execute('select approval_reference from capture_continuations').fetchall(),[(recovery.RESET_POLICY,)])
                    self.assertTrue(recovery.boundary(db,2))

    def test_untyped_reset_is_manual_and_another_fault_blocks_it(self):
        for later_fault in (False,True):
            with TemporaryDirectory() as tmp:
                store=Store(tmp)
                camera=Camera([True,ConnectionResetError(),True])
                worker=configure(Collector(store,camera,6))
                worker.once()
                worker.once()
                held=configure(Collector(Store(tmp),camera,6))
                self.assertTrue(held.stop.is_set())
                old=request(held)
                if later_fault:
                    probes=camera.probes
                    store.fail('camera_authentication_failed')
                    with self.assertRaisesRegex(ValueError,'continuation_later_failure'):
                        held.continue_after_gap(old)
                    self.assertEqual(camera.probes,probes)
                else:
                    accepted=held.continue_after_gap(old)
                    self.assertIsNone(accepted['gap_delta'])
                    self.assertEqual(camera.calls,2)
                    with self.assertRaises(ValueError):
                        held.continue_after_gap(old)
                    held.once()
                    with store.connect() as db:
                        self.assertTrue(recovery.boundary(db,2))
                        self.assertEqual(db.execute("select error from continuous_capture_outcomes where outcome='unknown'").fetchall(),[('ConnectionResetError',)])


class BoundTests(unittest.TestCase):
    def test_crossing_retains_all_reachable_turns(self):
        D=Decimal
        origin=(D('4.8'),D('4.9'))
        nxt=(D('0.1'),D('0.2'))
        self.assertEqual(advance_band(origin,nxt,D(5),D(1)),(D('5.1'),D('5.2')))
        self.assertEqual(advance_band(origin,nxt,D(5),D(6)),(D('5.1'),D('10.2')))
        self.assertIsNone(advance_band(origin,nxt,D(5),D('0.01')))

    def test_temporal_reading_inherits_conflicting_turn(self):
        fixture=turn_fixtures.DailyTurnRecoveryTests()
        rows=fixture.rows()
        source=lambda r:r['event_observation']
        values={i:(source(r),(Decimal(v),Decimal(v))) for r,i,v in zip(rows,(1,2,3,4),(0,1,1,4))}
        def read(first,last,document,source):
            return {eid:value for eid,value in values.items() if first<=eid<=last}
        edges=tail_edges(rows,fixture.format,Decimal(1),read)
        self.assertEqual(edges,[(2,3,Decimal(0),Decimal(0)),(2,4,Decimal(3),Decimal(3))])
        del values[4]
        self.assertEqual(tail_edges(rows,fixture.format,Decimal(1),read),[])
        self.assertIsNone(rows[-1]['unresolved_gap']['delta'])

    def test_held_chart_uses_the_acknowledged_day_and_matching_policy(self):
        pub=DailyPublisher(None)
        now=datetime.now(timezone.utc)
        pub.supported_source=dict(day=now.date().isoformat(),timezone='UTC',through=dict(format_id='format'),
                                  policy_sha256=_source_digest(pub.evidence_policy))
        self.assertTrue(pub.chart_sources('format','UTC')['chart_daily']['historical_only'])
        pub.supported_source['day']=(now-timedelta(days=1)).date().isoformat()
        self.assertEqual(set(pub.chart_sources('format','UTC')),{'chart_period_reference'})
        self.assertEqual(pub.chart_sources('other','UTC'),{})
        pub.supported_source['policy_sha256']='wrong'
        self.assertEqual(pub.chart_sources('format','UTC'),{})
