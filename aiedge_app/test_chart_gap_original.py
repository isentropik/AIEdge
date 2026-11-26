import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import Mock, patch

from chart_gap_original import GapOriginals, merge_bands, reachable_pairs


class GapOriginalTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE original_receipts(camera,frame,sha,size,proof_sha,event_id);
            CREATE TABLE compact_exposures(event_id,original_sha,packet_sha,pipeline);
            CREATE TABLE frames(camera,frame_id,sha256,bytes);
            CREATE TABLE capture_events(camera,frame_id,event_id);
            INSERT INTO original_receipts VALUES('cam','frame','jpeg',30,'packet',7);
            INSERT INTO compact_exposures VALUES(7,'jpeg','packet','pipe');
            INSERT INTO frames VALUES('cam','frame','jpeg',30);
            INSERT INTO capture_events VALUES('cam','frame',7);
        """)
        self.obs = dict(camera='cam',event_id=7,source_sha256='jpeg')
        self.doc = dict(pipeline_id='pipe',dials=[dict(index=1),dict(index=2),dict(index=0,position_error=.1)])
        mask = [True,False,True]
        support = dict(schema_version=1,observed=mask,pipeline_id='pipe',source_sha256='jpeg')
        self.result = dict(state='estimated',pipeline_id='pipe',source_sha256='jpeg',observation_support=support,
                           dial_positions=[dict(state='estimated',position=.03),dict(state='unavailable',position=None),
                                           dict(state='estimated',position=9.71)])
        self.reader = SimpleNamespace(pipeline_id='pipe',read_jpeg=Mock(return_value=self.result))
        self.store = SimpleNamespace(image=Mock(return_value=b'image'))
        self.originals = GapOriginals(self.store,SimpleNamespace(reader=self.reader))

    def pair(self,fine=9.99):
        return self.originals.pair(self.db,self.obs,self.doc,fine)

    def test_pair_validates_original_and_wrapped_fine_position(self):
        self.assertEqual(self.pair(),9.71)
        self.assertIsNone(self.pair(1))
        self.reader.read_jpeg.assert_called_once_with(b'image',observed=[True,False,True])

    def test_validated_original_must_still_have_a_matching_receipt(self):
        self.assertEqual(self.pair(),9.71)
        self.db.execute("UPDATE original_receipts SET proof_sha='wrong'")
        self.assertIsNone(self.pair())

    def test_missing_jpeg_or_incompatible_pipeline_withholds_evidence(self):
        self.store.image.side_effect=FileNotFoundError
        self.assertIsNone(self.pair())
        self.reader.pipeline_id='new'
        self.assertIsNone(self.pair())
        self.reader.read_jpeg.assert_not_called()

    def test_wrong_digest_or_missing_dial_withholds_evidence(self):
        self.result['source_sha256']='wrong'
        self.assertIsNone(self.pair())
        self.result['source_sha256']='jpeg'
        self.result['observation_support']['observed'][2]=False
        self.assertIsNone(self.pair())


class ClockBoundaryTests(unittest.TestCase):
    def test_overlapping_alternatives_merge_and_distinct_turns_survive(self):
        pairs=reachable_pairs([(D(1),D('1.05'))],(D('.95'),D('1.1')),D(5),D('5.01'))
        self.assertEqual(merge_bands(b for a,b in pairs),[(D(1),D('1.1')),(D('5.95'),D('6.06'))])
        self.assertEqual(merge_bands([(1,2),(1,3),(5,6)]),[(1,3),(5,6)])

    def test_interpolated_tick_requires_an_uninterrupted_sequence_after_anchor(self):
        clock=datetime(2026,11,25,14,10,tzinfo=timezone.utc)
        def sample(eid,offset):
            return (dict(event_id=eid,camera='meter',clock_id='epoch',context_id='ctx',
                         monotonic_us=(10+offset)*1000000,captured_at=(clock+timedelta(seconds=offset)).isoformat()),
                    (D('.95'),D('1.05')))
        originals=GapOriginals(None,None)
        originals.verified=Mock(return_value=(2,2))
        doc=dict(dials=[dict(index=0,value_per_revolution=1000,position_error=.1),
                        dict(index=1,value_per_revolution=5,position_error=.1)])
        db=Mock()
        samples=dict((i,sample(i,offset)) for i,offset in [(1,-8),(2,-2),(3,3)])
        with patch('chart_gap_original.phases',return_value=samples),patch('chart_gap_original.feasible_ranges',return_value={'intervals':[(D(1),D(1))]}):
            # The fake cursor always returns this camera's closest later exposure.
            def read(continued=True):
                db.execute.return_value.fetchone.side_effect=[(3,),None if continued else (1,)]
                return originals.next_boundary(db,{'camera':'meter'},doc,1,1,int(clock.timestamp()*1000),4)
            result=read()
            self.assertTrue(any(lo<=1<=hi for lo,hi in result['bands']))
            self.assertTrue(any(lo<=6<=hi for lo,hi in result['bands']))
            self.assertFalse(any(lo<=4.5<=hi for lo,hi in result['bands']))
            self.assertIsNone(read(False))
            samples[2][0]['clock_id']='reset'
            self.assertIsNone(read())
            del samples[2]
            self.assertIsNone(read())
