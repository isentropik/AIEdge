import copy
import json
from pathlib import Path
import unittest
from analyze_cycle_trial import analyze, distribution

ROOT = Path(__file__).resolve().parent
def initial():
    return dict(clock='monotonic_us_since_boot', active=False, attempts=0,
        pipeline_completed=0, failed=0, accepted_reader_cycles=0,
        overlaps_rejected=0, over_target=0, missed_schedule_slots=0,
        last=dict(start_us=0,end_us=0,capture_us=0,capture_interval_us=0,
                  reader_accepted=False,pipeline_completed=False))
def cycle(n, accepted=True):
    s=initial();s.update(attempts=n,pipeline_completed=n,accepted_reader_cycles=n if accepted else n-1)
    start=n*30_000_000
    s['last'].update(start_us=start,end_us=start+20_000_000,capture_us=start+1_000_000,
        capture_interval_us=30_000_000 if n>1 else 0, reader_accepted=accepted,pipeline_completed=True)
    return s

def run(snaps):return analyze(dict(same_boot_verified=True,snapshots=snaps))

class TrialTests(unittest.TestCase):
    def test_duplicate_poll_not_new_cycle(self):
        a=cycle(1); r=run([initial(),a,copy.deepcopy(a),cycle(2)])
        self.assertEqual(r['distinct_last_cycles'],2)
        self.assertEqual(r['observed_accepted_cycle_duration']['median_seconds'],20)
        self.assertEqual(r['observed_accepted_capture_to_pipeline_finish']['max_seconds'],19)
        self.assertEqual(r['software_acceptance_fraction'],1)
        self.assertIsNone(r['target_achieved'])
    def test_unobserved_failure_stays_in_denominator(self):
        b=cycle(3);b.update(pipeline_completed=2,failed=1,accepted_reader_cycles=2)
        r=run([initial(),cycle(1),b])
        self.assertEqual(r['window_unobserved_cycle_records'],1)
        self.assertEqual(r['software_acceptance_fraction'],2/3)
    def test_failed_and_unaccepted_excluded_from_success_times(self):
        a=cycle(1);a.update(pipeline_completed=0,failed=1,accepted_reader_cycles=0)
        a['last']['pipeline_completed']=False
        self.assertEqual(run([initial(),a])['observed_accepted_cycle_duration']['count'],0)
        self.assertEqual(run([initial(),cycle(1,False)])['software_acceptance_fraction'],0)
    def test_active_poll_does_not_erase_completed_cycle(self):
        a=cycle(1);b=copy.deepcopy(a);b.update(active=True,attempts=2)
        self.assertEqual(run([a,b])['distinct_last_cycles'],1)
        self.assertIsNone(run([a,b])['software_acceptance_fraction'])
    def test_bad_and_restarted_samples_rejected(self):
        cases=[]
        a=cycle(1);a['last']['capture_us']=a['last']['end_us']+1;cases.append([a])
        a=cycle(1);a['last']['capture_us']=0;cases.append([a])
        a=cycle(1);a['accepted_reader_cycles']=2;cases.append([a])
        cases.append([cycle(2),cycle(1)])
        a=cycle(1);b=copy.deepcopy(a);b['last']['end_us']+=1;cases.append([a,b])
        for case in cases:
            with self.subTest(case=case),self.assertRaises(ValueError):run(case)
        with self.assertRaises(ValueError):analyze({'same_boot_verified':False,'snapshots':[initial()]})
    def test_host_serializer_fixture(self):
        fixture=json.loads((ROOT/'telemetry-host-fixture.json').read_text())
        r=run([fixture['initial'],fixture['final']])
        self.assertEqual(r['window_finished_cycles'],5)
        self.assertEqual(r['window_unobserved_cycle_records'],4)
        self.assertEqual(r['software_acceptance_fraction'],.2)
        self.assertEqual(r['window_counter_deltas']['overlaps_rejected'],33)
    def test_boot_identity_cannot_be_overridden(self):
        a=initial();b=cycle(1)
        a['boot_id']=b['boot_id']='a'*32
        result=analyze({'snapshots':[a,b]})
        self.assertEqual(result['boot_continuity_evidence'],'firmware_boot_id')
        for identity in ('b'*32, None, 'bad'):
            b['boot_id']=identity
            with self.subTest(identity=identity),self.assertRaises(ValueError):run([a,b])

    def test_percentile_and_empty(self):
        self.assertEqual(distribution([i*1_000_000 for i in range(1,21)])['p95_seconds'],19)
        self.assertIsNone(distribution([])['p95_seconds'])

class StageTests(unittest.TestCase):
    def test_retry_failure_and_duplicate_poll(self):
        a=cycle(1)
        a['last'].update(stage_attempts=3,stages=[
            dict(index=0,duration_us=2_000_000,ok=True),
            dict(index=1,duration_us=4_000_000,ok=False),
            dict(index=1,duration_us=3_000_000,ok=True)])
        report=run([a,copy.deepcopy(a)])['observed_stages']
        self.assertEqual(report['cycles_with_stage_telemetry'],1)
        self.assertEqual(report['by_index']['1']['all_attempts']['count'],2)
        self.assertEqual(report['by_index']['1']['failed_attempts']['max_seconds'],4)
        self.assertEqual(report['by_index']['1']['successful_attempts']['max_seconds'],3)

    def test_legacy_missing_and_truncated_stages(self):
        a=cycle(2);a['last'].update(stage_attempts=18,stages=[dict(index=0,duration_us=1,ok=True)]*16)
        report=run([cycle(1),a])['observed_stages']
        self.assertEqual(report['cycles_without_stage_telemetry'],1)
        self.assertEqual(report['omitted_attempts_in_observed_cycles'],2)

    def test_invalid_stage_data_rejected(self):
        for stage in [dict(index=-1,duration_us=1,ok=True),dict(index=0,duration_us=-1,ok=True),
                      dict(index=0,duration_us=1,ok=1),dict(index=0,duration_us=21_000_000,ok=True)]:
            a=cycle(1);a['last'].update(stage_attempts=1,stages=[stage])
            with self.subTest(stage=stage),self.assertRaises(ValueError):run([a])
        a=cycle(1);a['last'].update(stage_attempts=0,stages=[dict(index=0,duration_us=1,ok=True)])
        with self.assertRaises(ValueError):run([a])

if __name__=='__main__':unittest.main()
