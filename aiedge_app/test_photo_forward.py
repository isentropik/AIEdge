import copy
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

import photo_forward as mod


class PhotoForwardTests(unittest.TestCase):
    def setUp(self):
        wall = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.rows, self.saved = {}, {}
        self.policy = dict(capacity_cfh=360, pipeline_id='pipeline', format_id='format')
        self.document = dict(unit='ft3', pipeline_id='pipeline', maximum_rate_per_second=.1, dials=[{}]*5+[
            dict(index=5, value_per_revolution=5, position_error=.1)])
        def put(event, seconds, pos):
            src = dict(event_id=event, captured_at=(wall+timedelta(seconds=seconds)).isoformat(),
                       monotonic_us=seconds*1000000, clock_id='epoch', camera='meter', source_sha256=str(event).zfill(64),
                       context_id='context', format_id='format')
            mask = [True]*6
            self.rows[event] = dict(event_observation=src, observation_support=dict(pipeline_id='pipeline', reader_observed=mask))
            self.saved[event] = dict(result=dict(state='estimated', event_observation=src.copy(),
                                            dial_positions=[{}]*5+[dict(position=pos)]))
            return src
        self.put = put
        self.origin = put(1, 1, 8)
        self.anchor = put(20, 100, 2)
        self.end = put(21, 110, 3)
        self.photo = dict(lower='11.90', upper='12.10', through=self.anchor, unresolved_lower='6.00',
                          unresolved_upper='18.10', assumption='Assumes ±4 ft³.', review_sha256='review')
        self.engine = mod.PhotoForward()
        self.calls = []
        def read(_, first, last, segment):
            self.calls.append((first,last,segment))
            return [v for e,v in self.rows.items() if first<=e<=last]
        self.enterContext(patch.object(mod,'daily_records',side_effect=read))
        self.enterContext(patch.object(mod,'read_batch',side_effect=lambda db, sources, pipeline:
                          [self.saved[s['event_id']] for s in sources]))
    def carry(self, target=None, seg='s', lo='0.00', hi='100.00'):
        target = target or self.end
        return self.engine.advance(None,self.document,self.policy,
            dict(start=self.origin,through=target,lower=lo,upper=hi),seg,dict(through=self.anchor),self.photo)

    def test_single_wrap_and_shared_endpoint_error(self):
        original = copy.deepcopy(self.photo)
        p = self.carry()
        self.assertEqual((p['lower'],p['upper']),('12.40','12.60'))
        self.assertEqual(p['through']['event_id'],21)
        self.assertEqual(p['reviewed_through'],self.anchor)
        self.assertEqual(self.photo,original)
        e = self.put(22,150,0)
        self.assertEqual((self.carry(e)['lower'],self.carry(e)['upper']),('15.90','16.10'))

    def test_ambiguous_gap_preserves_all_possible_turns(self):
        first = self.put(60,205,3)
        self.assertEqual(self.carry(first)['upper'],'17.60')
        del self.rows[60], self.saved[60]
        self.engine = mod.PhotoForward()
        end = self.put(60,215,3)
        state = self.carry(end)
        self.assertEqual((state['lower'],state['upper']),('12.40','22.60'))
        self.assertEqual((state['unresolved_lower'],state['unresolved_upper']),('0.00','100.00'))

    def test_missing_fine_reading_has_no_current_photo_timestamp(self):
        self.rows[21]['observation_support']['reader_observed'][-1] = False
        r = self.saved[21]['result']
        r['source_sha256']=self.end['source_sha256']
        r['pipeline_id']='pipeline'
        r['observation_support']=dict(schema_version=1,source_sha256=r['source_sha256'],pipeline_id='pipeline',
                                      observed=[True]*5+[False])
        r['dial_positions']=[dict(state='estimated',position=2)]*5+[dict(state='unavailable',position=None)]
        self.assertEqual(self.carry(),self.photo)
        later=self.put(22,160,3)
        self.assertEqual(self.carry(later)['upper'],'17.60')

    def test_wrong_observation_identity_clock_and_context(self):
        for key,value in [('source_sha256','different'),('format_id','other'),('monotonic_us',0),
                          ('clock_id','restart'),('context_id','other'),('captured_at',self.anchor['captured_at'])]:
            with self.subTest(key=key):
                self.engine=mod.PhotoForward()
                with patch.dict(self.end,{key:value}):
                    if key=='source_sha256':
                        self.assertEqual(self.carry(),self.photo)
                    else:
                        with patch.dict(self.saved[21]['result']['event_observation'],{key:value}):
                            self.assertEqual(self.carry(),self.photo)

    def test_incremental_catchup_restart_and_lineage(self):
        later=self.put(22,120,4)
        with patch.object(mod,'PAGE',1), patch.object(mod,'monotonic',side_effect=[0,2,3,5]):
            self.assertEqual(self.carry(later),self.photo)
            final=self.carry(later)
        self.assertEqual(final['through']['event_id'],22)
        self.calls.clear()
        self.assertEqual(self.carry(later),final)
        self.assertEqual(self.calls,[])
        self.assertEqual(self.carry(later,'new-lineage'),final)
        self.assertIn((1,1,'new-lineage'),self.calls)
        self.engine=mod.PhotoForward()
        self.assertEqual(self.carry(later),final)
        self.assertEqual(self.carry()['through']['event_id'],21)

    def test_incompatible_format_or_missing_anchor_fails_closed(self):
        with patch.dict(self.document,unit='m3'):
            self.assertEqual(self.carry(),self.photo)
        with patch.dict(self.rows[20],event_observation=dict(self.anchor,source_sha256='different')):
            self.assertEqual(self.carry(),self.photo)

    def test_contradictory_or_narrower_unresolved_bounds(self):
        self.assertEqual(self.carry(lo='12.70'),self.photo)
        p=self.carry(lo='12.43',hi='12.55')
        self.assertEqual((p['lower'],p['upper']),('12.43','12.55'))
