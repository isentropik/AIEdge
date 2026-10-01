"""Independent physical trajectories exercise bounds, not image accuracy."""
import copy,random,unittest
from temporal_reading import TemporalReading


def document(scales=(1000,5),errors=(.1,.1)):
    return {'version':1,'pipeline_id':'a'*64,'unit':'ft3','dials':[
        {'index':i,'value_per_revolution':p,'position_error':e}
        for i,(p,e) in enumerate(zip(scales,errors))]}


def amount(low,high):return {'minimum':low,'maximum':high,'upper_unbounded':high is None}


def positions(total,scales=(1000,5)):
    return [(total%p)/p*10 for p in scales]


class TemporalTests(unittest.TestCase):
    def contains(self,result,quantity,period=1000):
        self.assertIn(result['state'],('ambiguous','estimated'))
        target=quantity%period
        self.assertTrue(any(row['lower']-1e-9<=target<=row['upper']+1e-9
                            for row in result['bounds']['ranges']),(target,result))
        self.assertFalse(result['accuracy_verified']);self.assertFalse(result['training_allowed'])

    def test_subsequent_register_observation_can_select_one_starting_offset(self):
        tracker=TemporalReading(document())
        initial=tracker.observe([1.194,9],amount(0,0))
        self.assertEqual(initial['state'],'ambiguous');self.assertGreater(len(initial['bounds']['ranges']),1)
        # True totals 109.5 -> 110.5, with opposing in-tolerance noise on
        # the larger dial. Known cumulative bounds are supplied, not inferred
        # from an assumed whole wheel turn.
        current=tracker.observe([1.006,1],amount(.9,1.1))
        self.assertEqual(current['state'],'estimated');self.assertTrue(current['anchor_refined'])
        self.assertAlmostEqual(current['value'],110.5);self.contains(current,110.5)

    def test_stationary_duplicates_do_not_identify_a_missing_whole_turn(self):
        tracker=TemporalReading(document());initial=tracker.observe([1.095,9],amount(0,0))
        for _ in range(20):
            current=tracker.observe([1.095,9],amount(0,.1))
            self.assertEqual(current['state'],'ambiguous')
            self.assertEqual(current['bounds']['ranges'],initial['bounds']['ranges'])
            self.assertFalse(current['anchor_refined']);self.assertIsNone(current['value'])

    def test_unbounded_consumption_never_uses_history_to_select_turns(self):
        tracker=TemporalReading(document());tracker.observe([1.194,9],amount(0,0))
        result=tracker.observe([1.006,1],amount(.9,None))
        self.assertEqual(result['state'],'ambiguous');self.assertIsNone(result['value'])
        self.assertEqual(result['provenance'],'single_image_unbounded_consumption')
        self.assertFalse(result['anchor_refined'])

    def test_whole_register_rollover_is_forward_without_double_counting(self):
        tracker=TemporalReading(document(errors=(.001,.01)))
        first=tracker.observe(positions(999.8),amount(0,0));self.contains(first,999.8)
        current=tracker.observe(positions(1000.2),amount(.39,.41))
        self.contains(current,1000.2);self.assertAlmostEqual(current['value'],.2)

    def test_conflicting_frame_and_work_limit_leave_anchor_unchanged(self):
        tracker=TemporalReading(document());tracker.observe([1.095,9],amount(0,0))
        anchor=copy.deepcopy(tracker.anchor)
        bad=tracker.observe([7,0],amount(.9,1.1))
        self.assertEqual(bad['reason'],'temporal_bounds_disagree');self.assertEqual(tracker.anchor,anchor)
        limit=tracker.observe([1.105,1],amount(0,1e20))
        self.assertEqual(limit['reason'],'temporal_range_limit');self.assertEqual(tracker.anchor,anchor)
        self.assertEqual(tracker.observations,1)

    def test_no_good_anchor_does_not_turn_a_later_consumption_value_into_zero(self):
        tracker=TemporalReading(document((10000,1000,5),(.01,.1,.01)))
        self.assertEqual(tracker.observe([9,1,0],amount(0,0))['state'],'unavailable')
        later=tracker.observe(positions(9011,(10000,1000,5)),amount(.9,1.1))
        self.assertEqual(later['reason'],'temporal_anchor_unavailable');self.assertIsNone(tracker.anchor)

    def test_replay_and_restart_produce_identical_decisions(self):
        samples=[([1.194,9],amount(0,0)),([1.006,1],amount(.9,1.1)),([1.016,3],amount(1.9,2.1))]
        first=TemporalReading(document());second=TemporalReading(document())
        self.assertEqual([first.observe(*s) for s in samples],[second.observe(*s) for s in samples])

    def test_multiple_missing_wheel_turns_remain_multiple_offsets(self):
        tracker=TemporalReading(document());tracker.observe([1.095,9],amount(0,0))
        current=tracker.observe([1.115,3],amount(1.9,12.1))
        self.assertEqual(current['state'],'ambiguous');self.assertIsNone(current['value'])
        self.contains(current,111.5);self.contains(current,116.5)

    def test_seeded_independent_trajectories_keep_true_total_inside_bounds(self):
        rng=random.Random(1445)
        scales=(10000,1000,5);errors=(.03,.1,.02)
        for scene in range(40):
            anchor=rng.uniform(0,10000);total=anchor;tracker=TemporalReading(document(scales,errors))
            for frame in range(12):
                if frame:total+=rng.uniform(0,2)
                sample=[(p+rng.uniform(-e,e))%10 for p,e in zip(positions(total,scales),errors)]
                delta=total-anchor
                bounds=amount(0,0) if not frame else amount(max(0,delta-.03),delta+.03)
                result=tracker.observe(sample,bounds)
                self.contains(result,total,10000)

    def test_invalid_observations_fail_before_mutating_state(self):
        tracker=TemporalReading(document())
        for values,bounds in [([1],amount(0,0)),([True,0],amount(0,0)),([1,float('nan')],amount(0,0)),
                              ([1,0],amount(-1,0)),([1,0],amount(1,.5)),([1,0],amount(0,float('inf'))),
                              ([1,0],{'minimum':0,'maximum':None,'upper_unbounded':False})]:
            with self.subTest(values=values,bounds=bounds),self.assertRaises(ValueError):tracker.observe(values,bounds)
            self.assertIsNone(tracker.anchor)

    def test_large_legal_format_cannot_overflow_the_durable_record(self):
        tracker=TemporalReading(document((1e100,1e96),(.1,.1)))
        result=tracker.observe([5,5],amount(0,0))
        self.assertEqual(result['state'],'unavailable');self.assertEqual(result['reason'],'temporal_result_limit')
        self.assertNotIn('bounds',result);self.assertIsNone(result['value'])


class PublicationTests(unittest.TestCase):
    def setUp(self):
        from reading_format import reconcile_reading
        self.combine=reconcile_reading
        self.reading={'state':'ambiguous','value':None,'unit':'ft3','format_id':'a'*64,
                      'source_sha256':'b'*64,'accuracy_verified':False,'training_allowed':False}
        tracker=TemporalReading(document());tracker.observe([1.194,9],amount(0,0))
        self.consumption={'state':'estimated','format_id':'a'*64,'source_sha256':'b'*64,
                          'absolute':tracker.observe([1.006,1],amount(.9,1.1))}

    def test_current_matching_refinement_becomes_a_conditional_estimate(self):
        from mqtt_output import fresh_state
        from datetime import datetime,timezone
        result=self.combine(self.reading,self.consumption)
        self.assertEqual(result['state'],'estimated');self.assertAlmostEqual(result['value'],110.5)
        self.assertFalse(result['accuracy_verified']);self.assertFalse(result['training_allowed'])
        snapshot={'reading':result,'latest':{'sha256':'b'*64,'captured_at':datetime.now(timezone.utc).isoformat()}}
        self.assertAlmostEqual(fresh_state(snapshot,90)['value'],110.5)

    def test_pending_rejected_and_mismatched_observations_never_publish_an_old_total(self):
        for key,value in [('state','pending'),('state','recovering'),('state','unavailable'),
                          ('format_id','c'*64),('source_sha256','c'*64)]:
            with self.subTest(key=key,value=value):
                self.assertEqual(self.combine(self.reading,{**self.consumption,key:value}),self.reading)

    def test_ambiguous_offsets_and_unbounded_history_never_become_an_estimate(self):
        from mqtt_output import fresh_state
        tracker=TemporalReading(document());tracker.observe([1.095,9],amount(0,0))
        for bounds in (amount(1.9,12.1),amount(1.9,None)):
            consumption={**self.consumption,'absolute':tracker.observe([1.115,3],bounds)}
            result=self.combine(self.reading,consumption)
            self.assertEqual(result['state'],'ambiguous');self.assertIsNone(result['value'])
            self.assertIsNone(fresh_state({'reading':result,'latest':{}},90))

    def test_single_image_point_and_false_accuracy_claims_are_not_rewritten(self):
        single={**self.reading,'state':'estimated','value':42}
        self.assertEqual(self.combine(single,self.consumption),single)
        for flag in ('accuracy_verified','training_allowed'):
            value=copy.deepcopy(self.consumption);value['absolute'][flag]=True
            self.assertEqual(self.combine(self.reading,value),self.reading)

    def test_status_http_uses_the_current_refinement_and_clears_it_when_pending(self):
        import json,tempfile,threading,urllib.request
        from http.server import ThreadingHTTPServer
        from types import SimpleNamespace
        from capture import Store
        from service import handler
        with tempfile.TemporaryDirectory() as directory:
            consumption=SimpleNamespace(status=lambda:self.consumption)
            formats=SimpleNamespace(evaluate=lambda _:self.reading,status=lambda:{})
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(Store(directory),False,None,
                                      reading_format=formats,consumption=consumption))
            thread=threading.Thread(target=lambda:server.serve_forever(poll_interval=.01));thread.start()
            try:
                url=f'http://127.0.0.1:{server.server_port}/api/status'
                with urllib.request.urlopen(url) as response:state=json.load(response)
                self.assertEqual(state['reading']['state'],'estimated')
                self.assertAlmostEqual(state['reading']['value'],110.5)
                self.assertFalse(state['capture_enabled']);self.assertEqual(state['mqtt']['state'],'disabled')
                self.consumption['state']='pending'
                with urllib.request.urlopen(url) as response:state=json.load(response)
                self.assertEqual(state['reading']['state'],'ambiguous');self.assertIsNone(state['reading']['value'])
            finally:server.shutdown();thread.join();server.server_close()


if __name__=='__main__':unittest.main()
