from decimal import Decimal as D
import unittest
from unittest.mock import patch
from test_absolute_motion import Store, source
from absolute_motion import meter_rate, start
from reading_format import validate
import register_replay as replay

class RegisterReplayTests(unittest.TestCase):
    def setUp(self):
        self.doc = dict(version=1, pipeline_id='a'*64, unit='ft3', maximum_rate_per_second=.5,
                        dials=[dict(index=0, value_per_revolution=5, position_error=.1)])
        self.fmt = validate(self.doc)[1]
        self.store = Store()
        self.addCleanup(self.store.db.close)
        self.rate = D('.2')
        self.src = lambda k: source(k, format_id=self.fmt)
        self.band = (D('0'), D('.1'))
        self.old = start(self.src(1), [(D(100),D('100.1'))], 0)
        self.old.update(source=self.src(70), outer=['100','2400'])
        self.seed = patch.object(replay, 'seed', return_value=(self.src(1), (D(95),D('100.1'))))
        self.seed.start()
        self.addCleanup(self.seed.stop)
        self.phases = patch.object(replay, 'phases', side_effect=lambda db,a,b,*_,**kwargs: {
            i:(self.src(i),self.band) for i in range(a,b+1)})
        self.phases.start()
        self.addCleanup(self.phases.stop)

    def test_meter_rate_uses_format_maximum(self):
        self.assertEqual(meter_rate(self.doc), D('.5'))

    def test_old_checkpoint_replays_in_pages_and_keeps_both_turns(self):
        from copy import deepcopy
        first = replay.refine(self.store,self.doc,self.old,self.rate)
        self.assertEqual(first['display'],self.old['display'])
        self.assertEqual(first['envelope_replay']['source']['event_id'],65)
        fixed = replay.refine(self.store,self.doc,deepcopy(first),self.rate)
        self.assertEqual(fixed['outer'],['95','100.1'])
        self.assertEqual(fixed['level'],self.old['level'])
        self.assertEqual(fixed['display']['source_sha256'],self.src(70)['source_sha256'])
        self.assertEqual(fixed['envelope_replay']['source'],fixed['source'])
        self.assertEqual(replay.refine(self.store,self.doc,fixed,self.rate),fixed)

    def test_gap_segment_or_clock_reset_leaves_original_bounds(self):
        for table,col in [('capture_failure_boundaries','after_event_id'),('consumption_segment_links','first_event')]:
            with self.subTest(table=table):
                self.store.db.execute('insert into '+table+' ('+col+') values (12)')
                result=replay.refine(self.store,self.doc,self.old,self.rate)
                self.assertEqual(result['outer'],self.old['outer'])
                self.assertTrue(result['envelope_replay']['stopped'])
                self.store.db.execute('delete from '+table)
        with patch.object(replay,'phases',return_value={2:(dict(self.src(2),clock_id='reset'),self.band)}):
            self.assertTrue(replay.refine(self.store,self.doc,self.old,self.rate)['envelope_replay']['stopped'])
        with patch.object(replay,'phases',return_value={}):
            self.assertEqual(replay.refine(self.store,self.doc,self.old,self.rate)['display'],self.old['display'])

    def test_mismatched_anchor_or_head_cannot_replace_checkpoint(self):
        with patch.object(replay,'seed',return_value=(dict(self.src(1),source_sha256='b'*64),self.band)):
            self.assertEqual(replay.refine(self.store,self.doc,self.old,self.rate)['outer'],self.old['outer'])
        track=dict(self.old,source=dict(self.src(2),source_sha256='c'*64))
        self.assertEqual(replay.refine(self.store,self.doc,track,self.rate)['outer'],self.old['outer'])

    def test_later_full_reading_resolves_a_turn_or_stops_on_a_disagreement(self):
        def page_with_photo(band):
            def saved(db, a, b, *args, absolute_bands):
                absolute_bands[2]=[band]
                return {i:(self.src(i),self.band) for i in range(a,b+1)}
            with patch.object(replay,'phases',saved):
                return replay.page(self.store.db,self.doc,self.src(1),(D(95),D('100.1')),3,self.rate)
        rows=page_with_photo((D(95),D('95.1')))
        self.assertEqual(rows[-1][1],(D(95),D('95.1')))
        self.assertEqual(page_with_photo((D(90),D('90.1'))),[])

    def test_slower_observations_bound_repeated_possible_fine_wraps_across_pages(self):
        doc = dict(self.doc, dials=[dict(value_per_revolution=1000), self.doc['dials'][0]])
        def samples(db, first, last, *args, absolute_bands, slow_phases):
            for event in range(first,last+1):
                if event % 3 == 1:
                    slow_phases[event] = (D('9.9'),D('10.1'))
            return {i:(self.src(i),self.band) for i in range(first,last+1)}
        with patch.object(replay, 'phases', samples):
            rate = D('.6')
            track = replay.refine(self.store,doc,self.old,rate)
            fixed = replay.refine(self.store,doc,track,rate)
            self.assertEqual(fixed['outer'],['95','100.1'])
            self.assertEqual(fixed['display']['bounds_flow_limit_cfh'],2160)
            self.assertEqual(fixed['envelope_replay']['slow']['tick'],self.src(70)['monotonic_us'])

    def test_conflicting_full_decode_keeps_corroborated_motion_until_next_full_photo(self):
        doc = dict(self.doc, dials=[dict(value_per_revolution=1000), self.doc['dials'][0]])
        earlier_decode = (D(90), D('90.1'))
        def samples(db, first, last, *args, absolute_bands, slow_phases):
            for i in range(first, last+1):
                slow_phases[i] = (D('9.9'), D('10.1'))
                if i == 2:
                    absolute_bands[i] = [earlier_decode]
                if i == 3:
                    absolute_bands[i] = [(D(100), D('100.1'))]
            return {i:(self.src(i),self.band) for i in range(first,last+1)}
        with patch.object(replay, 'phases', samples):
            slow = {}
            initial = (D(95), D('100.1'))
            first, = replay.page(self.store.db, doc, self.src(1), initial, 2, self.rate, slow)
            self.assertEqual(first, (self.src(2), initial))
            self.assertEqual(slow['base'], list(map(str, initial)))
            next_photo, = replay.page(self.store.db, doc, *first, 3, self.rate, slow)
            self.assertEqual(next_photo, (self.src(3), (D(100), D('100.1'))))
            self.assertEqual(slow['base'], ['100','100.1'])
            earlier_decode = (D(110), D('110.1'))
            self.assertEqual(replay.page(self.store.db, doc, self.src(1), initial, 2, self.rate, {}), [])

    def test_previous_version_stopped_checkpoint_is_replayed(self):
        anchor = self.old['anchor']
        old_key = [anchor['event_id'], anchor['source_sha256'], anchor['captured_at'], str(self.rate)]
        track = dict(self.old, envelope_replay=dict(key=old_key, stopped=True))
        first = replay.refine(self.store, self.doc, track, self.rate)
        self.assertNotEqual(first['envelope_replay']['key'], old_key)
        fixed = replay.refine(self.store, self.doc, first, self.rate)
        self.assertEqual(fixed['outer'], ['95','100.1'])

    def test_cold_chart_reads_the_same_original_as_publication(self):
        from threading import Event
        from datetime import datetime
        originals = object()
        chart = replay.ChartRegisterReplay(self.store, originals)
        src = self.src(1)
        point = (int(datetime.fromisoformat(src['captured_at']).timestamp()*1000), D('100.05'),
                 (D(0),D(200)), 1, False, (0,'photo_anchored_fine_dial'), src['source_sha256'])
        head = dict(event_id=1, anchor_event_id=1, anchor_source_sha256=src['source_sha256'],
                    anchor_measured_at=src['captured_at'])
        with patch.object(replay, 'seed', return_value=(src, (D(100),D('100.1')))) as lookup:
            result = chart.readings([point],head,self.doc,{},Event())
        self.assertIs(lookup.call_args.args[-1], originals)
        self.assertEqual(result[0][2], (D(100),D('100.1')))
