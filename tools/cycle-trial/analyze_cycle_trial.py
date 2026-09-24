"""Offline analysis of ordered cycle snapshots from one externally verified boot.

Input: {"snapshots": [cycle_timing JSON with matching boot_id, ...]}.
Legacy records require an explicit independently verified same_boot_verified flag.
Never polls devices. Software acceptance is not reading accuracy or MQTT delivery.
"""
import argparse
import json
import math
import re
from pathlib import Path

COUNTERS = ('attempts', 'pipeline_completed', 'failed', 'accepted_reader_cycles',
            'overlaps_rejected', 'over_target', 'missed_schedule_slots')

def distribution(values):
    if not values:
        return {'count': 0, 'median_seconds': None, 'p95_seconds': None, 'max_seconds': None}
    values = sorted(values)
    n = len(values)
    median = (values[(n-1)//2] + values[n//2]) / 2
    return {'count': n, 'median_seconds': median/1e6,
            'p95_seconds': values[math.ceil(.95*n)-1]/1e6, 'max_seconds': values[-1]/1e6}

def integer(value):
    return type(value) is int and 0 <= value < 2**64

def analyze(document):
    snapshots = document['snapshots']
    if not snapshots:
        raise ValueError('No snapshots')
    identities=[s.get('boot_id') for s in snapshots]
    if any(i is not None for i in identities):
        if not all(isinstance(i,str) and re.fullmatch('[0-9a-f]{32}',i) for i in identities):
            raise ValueError('Missing or malformed boot identity in telemetry')
        if len(set(identities)) != 1:
            raise ValueError('Different boot identities; analyze each boot separately')
        boot_evidence='firmware_boot_id'
    elif document.get('same_boot_verified') is True:
        boot_evidence='external_assertion_legacy'
    else:
        raise ValueError('Boot continuity must be independently verified; do not compare uptime across restarts')

    previous = None
    seen = {}
    cycles, accepted, intervals, latency = [], [], [], []
    stage_samples = {}
    stage_cycles = 0
    omitted_stage_attempts = 0
    for snap in snapshots:
        if snap['clock'] != 'monotonic_us_since_boot' or type(snap['active']) is not bool:
            raise ValueError('Unsupported clock or active flag')
        if not all(integer(snap[k]) for k in COUNTERS):
            raise ValueError('Invalid counter')
        finished = snap['pipeline_completed'] + snap['failed']
        if snap['attempts'] != finished + int(snap['active']):
            raise ValueError('Inconsistent attempted/completed/active counts')
        if snap['accepted_reader_cycles'] > snap['pipeline_completed'] or snap['over_target'] > finished:
            raise ValueError('Inconsistent accepted/deadline counts')
        if previous and any(snap[k] < previous[k] for k in COUNTERS):
            raise ValueError('Counter regression: restart, stale sample, or corruption')
        last = snap['last']
        for key in ('start_us', 'end_us', 'capture_us', 'capture_interval_us'):
            if not integer(last[key]):
                raise ValueError('Invalid monotonic timestamp')
        if type(last['reader_accepted']) is not bool or type(last['pipeline_completed']) is not bool:
            raise ValueError('Invalid last-cycle flags')
        start, end, capture = (last[k] for k in ('start_us', 'end_us', 'capture_us'))
        stages = last.get('stages')
        if 'stages' in last or 'stage_attempts' in last:
            attempts = last.get('stage_attempts')
            if not integer(attempts) or not isinstance(stages, list) or len(stages) > 16 or len(stages) > attempts:
                raise ValueError('Invalid stage records or attempt count')
            for stage in stages:
                if not isinstance(stage, dict) or not integer(stage.get('index')) or not integer(stage.get('duration_us')) or type(stage.get('ok')) is not bool:
                    raise ValueError('Invalid stage timing')
            if sum(stage['duration_us'] for stage in stages) > end-start:
                raise ValueError('Recorded stage time exceeds cycle duration')
            if not finished and attempts:
                raise ValueError('Stage attempts without a completed cycle')
        if not finished:
            if start or end or capture:
                raise ValueError('Unexpected last cycle before any completion')
        else:
            if end < start or not end or (capture and not start <= capture <= end):
                raise ValueError('Invalid last-cycle ordering')
            if last['reader_accepted'] and not capture:
                raise ValueError('Accepted reader without capture')
            if finished in seen and seen[finished] != last:
                raise ValueError('Same completed-cycle count changed its record')
            if finished not in seen:
                if seen and start < max(r['end_us'] for r in seen.values()):
                    raise ValueError('Overlapping or stale completed-cycle record')
                seen[finished] = last
                cycles.append(end-start)
                if stages is not None:
                    stage_cycles += 1
                    omitted_stage_attempts += last['stage_attempts']-len(stages)
                    for stage in stages:
                        samples = stage_samples.setdefault(stage['index'], {'ok': [], 'failed': []})
                        samples['ok' if stage['ok'] else 'failed'].append(stage['duration_us'])
                if last['reader_accepted'] and last['pipeline_completed']:
                    accepted.append(end-start)
                    latency.append(end-capture)
                if last['capture_interval_us']:
                    if not capture or last['capture_interval_us'] >= capture:
                        raise ValueError('Invalid capture interval')
                    intervals.append(last['capture_interval_us'])
        previous = snap
    first, final = snapshots[0], snapshots[-1]
    deltas = {k: final[k]-first[k] for k in COUNTERS}
    first_finished = first['pipeline_completed'] + first['failed']
    final_finished = final['pipeline_completed'] + final['failed']
    observed_window = sum(k > first_finished for k in seen)
    finished_delta = final_finished-first_finished
    return {'boot_id':identities[0], 'boot_continuity_evidence':boot_evidence, 'snapshots': len(snapshots), 'distinct_last_cycles': len(seen),
        'window_counter_deltas': deltas, 'window_finished_cycles': finished_delta,
        'window_unobserved_cycle_records': finished_delta-observed_window,
        'software_acceptance_fraction': deltas['accepted_reader_cycles']/finished_delta if finished_delta else None,
        'observed_cycle_duration': distribution(cycles),
        'observed_accepted_cycle_duration': distribution(accepted),
        'observed_accepted_capture_to_pipeline_finish': distribution(latency),
        'observed_capture_intervals': distribution(intervals),
        'observed_stages': {
            'cycles_with_stage_telemetry': stage_cycles,
            'cycles_without_stage_telemetry': len(seen)-stage_cycles,
            'omitted_attempts_in_observed_cycles': omitted_stage_attempts,
            'by_index': {str(index): {
                'all_attempts': distribution(samples['ok']+samples['failed']),
                'successful_attempts': distribution(samples['ok']),
                'failed_attempts': distribution(samples['failed'])
            } for index, samples in sorted(stage_samples.items())},
            'scope': 'Stage indexes follow the configured pipeline; names are not inferred. Retries are separate attempts, not separate cycles.'
        },
        'verified_accuracy': None, 'mqtt_delivery_verified': False, 'target_achieved': None,
        'limits': ['Only observed last-cycle records contribute to distributions; missed records can bias percentiles',
                   'Counter deltas exclude work already completed at the first snapshot',
                   'Capture interval can precede the first snapshot; no cross-boot duration is inferred',
                   'Reader acceptance does not establish physical accuracy or publication receipt',
                   'A finite trial alone cannot guarantee sustained 30-second performance']}

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = analyze(json.loads(args.input.read_text()))
    with args.output.open('x') as output:
        json.dump(report, output, indent=2)
    print(json.dumps(report, indent=2))
