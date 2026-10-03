"""Bounded in-memory same-host durations; no logs, identifiers or disk writes."""
from collections import deque
from contextlib import contextmanager
import math
import threading
import time
from types import SimpleNamespace

STAGES = frozenset(('camera_readiness', 'capture', 'reference_capture',
                    'camera_headers', 'reference_headers', 'camera_download',
                    'reference_download', 'storage', 'image_validation',
                    'recognition', 'read_and_infer', 'inference_commit'))
OUTCOMES = frozenset(('success', 'failure', 'duplicate', 'rejected'))
WINDOW = 64


class Timings:
    def __init__(self, clock=time.perf_counter):
        self.clock = clock
        self.lock = threading.Lock()
        self.samples = {stage: deque(maxlen=WINDOW) for stage in STAGES}
        self.counts = {stage: {outcome: 0 for outcome in OUTCOMES} for stage in STAGES}

    def record(self, stage, seconds, outcome='success'):
        # Reject arbitrary labels/values so diagnostics cannot leak response
        # bodies, filenames, credentials or invalid JSON through telemetry.
        if not isinstance(stage, str) or not isinstance(outcome, str) or stage not in STAGES or outcome not in OUTCOMES:
            return False
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
            return False
        with self.lock:
            self.samples[stage].append((seconds, outcome))
            self.counts[stage][outcome] += 1
        return True

    @contextmanager
    def measure(self, stage):
        if stage not in STAGES:
            raise ValueError('unknown_performance_stage')
        sample = SimpleNamespace(outcome='success')
        start = self.clock()
        try:
            yield sample
        except BaseException:
            sample.outcome = 'failure'
            raise
        finally:
            self.record(stage, self.clock() - start, sample.outcome)

    def snapshot(self):
        with self.lock:
            samples = {stage: list(values) for stage, values in self.samples.items()}
            counts = {stage: dict(values) for stage, values in self.counts.items()}
        stages = {}
        for stage in sorted(STAGES):
            if not samples[stage]:
                continue
            outcomes = {}
            for outcome in sorted(OUTCOMES):
                values = sorted(seconds for seconds, result in samples[stage] if result == outcome)
                if values:
                    middle = len(values) // 2
                    median = (values[middle] if len(values) % 2 else
                              values[middle - 1] / 2 + values[middle] / 2)
                    # Nearest-rank p95 for the retained observations of this
                    # outcome. Failure/duplicate durations never improve success.
                    outcomes[outcome] = {'samples': len(values), 'minimum_seconds': values[0],
                        'median_seconds': median,
                        'p95_seconds': values[math.ceil(.95 * len(values)) - 1],
                        'maximum_seconds': values[-1]}
            stages[stage] = {'counts_since_start': counts[stage],
                             'retained_samples': len(samples[stage]), 'outcomes': outcomes}
        return {'state': 'measured' if stages else 'not_measured', 'clock': 'host_monotonic',
                'scope': 'current_recorder_session', 'window_per_stage': WINDOW,
                'stages': stages, 'stage_durations_overlap': True,
                'end_to_end_publication_measured': False,
                'reading_accuracy_verified': False,
                'unmeasured': ['camera_internal_stages', 'recognition_queue_wait',
                               'accounting', 'mqtt_publication']}
