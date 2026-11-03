"""Bounded in-memory same-host durations; no logs, identifiers or disk writes."""
from collections import deque, OrderedDict
from contextlib import contextmanager
import math
import re
import threading
import time
from types import SimpleNamespace

STAGES = frozenset(('camera_readiness', 'capture', 'reference_capture',
                    'camera_headers', 'reference_headers', 'camera_download',
                    'reference_download', 'storage', 'image_validation',
                    'recognition', 'read_and_infer', 'inference_commit',
                    'recognition_queue_wait', 'accounting', 'mqtt_publication',
                    'capture_request_to_broker_ack'))
OUTCOMES = frozenset(('success', 'failure', 'duplicate', 'rejected'))
WINDOW = 64
TRANSFER_WINDOW = 8


class _TransferReads:
    """Counts application read1 waits and delivered bytes, never TCP packets."""
    def __init__(self, clock, expected, reference):
        self.clock = clock
        self.started = clock()
        self.expected = expected
        self.reference = reference
        self.received = self.calls = 0
        self.first_delivery = self.last_delivery = None
        self.maximum_wait = 0.0

    def read1(self, response, size):
        before = self.clock()
        self.calls += 1
        try:
            block = response.read1(size)
        finally:
            after = self.clock()
            self.maximum_wait = max(self.maximum_wait, after - before)
        if block:
            self.received += len(block)
            if self.first_delivery is None:
                self.first_delivery = after
            self.last_delivery = after
        return block

    def finish(self, outcome):
        ended = self.clock()
        return dict(expected_bytes=self.expected, application_bytes=self.received,
            reference=self.reference, read_calls=self.calls, outcome=outcome,
            elapsed_seconds=ended-self.started,
            maximum_read_wait_seconds=self.maximum_wait,
            first_delivery_seconds=None if self.first_delivery is None else self.first_delivery-self.started,
            since_last_delivery_seconds=None if self.last_delivery is None else ended-self.last_delivery)


class Timings:
    def __init__(self, clock=time.perf_counter):
        self.clock = clock
        self.lock = threading.Lock()
        self.traces = OrderedDict()
        self.trace_evictions = 0
        self.transfer_samples = deque(maxlen=TRANSFER_WINDOW)
        self.transfer_count = 0
        self.last_capture_body_timeout = None
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

    @contextmanager
    def transfer_reads(self, expected, reference=False):
        trace = _TransferReads(self.clock, expected, reference)
        outcome = 'failure'
        try:
            yield trace
            outcome = 'complete' if trace.received == expected else 'incomplete'
        except TimeoutError:
            outcome = 'timeout'
            raise
        finally:
            result = trace.finish(outcome)
            with self.lock:
                self.transfer_count += 1
                result['sequence'] = self.transfer_count
                self.transfer_samples.append(result)
                if outcome == 'timeout' and not reference:
                    self.last_capture_body_timeout = result

    def snapshot(self):
        with self.lock:
            samples = {stage: list(values) for stage, values in self.samples.items()}
            counts = {stage: dict(values) for stage, values in self.counts.items()}
            evictions = self.trace_evictions
            transfers = [dict(row) for row in self.transfer_samples]
            transfer_count = self.transfer_count
            timeout = self.last_capture_body_timeout
            last_timeout = None if timeout is None else dict(timeout)
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
                'end_to_end_publication_measured': counts['capture_request_to_broker_ack']['success'] > 0,
                'publication_endpoint': 'broker_acknowledgement',
                'publication_start': 'app_host_capture_request',
                'ha_entity_receipt_measured': False,
                'trace_window': WINDOW, 'trace_evictions_since_start': evictions,
                'transfer_reads': {'scope': 'application_read1_only',
                    'window': TRANSFER_WINDOW, 'count_since_start': transfer_count,
                    'samples': transfers, 'tcp_packet_timing_measured': False,
                    'last_capture_body_timeout': last_timeout,
                    'camera_internal_timing_measured': False},
                'reading_accuracy_verified': False,
                'unmeasured': ['camera_internal_stages', 'ha_entity_receipt']}

    def admit(self, event, digest, request_started=None):
        # Identifiers are private correlation keys and never appear in snapshots.
        if type(event) is not int or event < 1 or not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
            return False
        current = self.clock()
        if type(request_started) not in (int, float) or not math.isfinite(request_started) or not 0 <= request_started <= current:
            request_started = None
        with self.lock:
            if event in self.traces:
                return False
            self.traces[event] = dict(digest=digest, admitted=current, started=request_started,
                                      dispatched=False, acknowledged=False)
            if len(self.traces) > WINDOW:
                self.traces.popitem(last=False)
                self.trace_evictions += 1
        return True

    def begin_recognition(self, digest):
        current = self.clock()
        with self.lock:
            # Recognition prioritizes the newest capture, then oldest backlog.
            trace = next((value for value in reversed(self.traces.values())
                          if value['digest'] == digest), None)
            if trace is None or trace['dispatched']:
                return False
            seconds = current - trace['admitted']
            if seconds < 0:
                return False
            trace['dispatched'] = True
        return self.record('recognition_queue_wait', seconds)

    def publication_ack(self, event, digest):
        if type(event) is not int:
            return False
        current = self.clock()
        with self.lock:
            trace = self.traces.get(event)
            if trace is None or trace['digest'] != digest or trace['acknowledged'] or trace['started'] is None:
                return False
            seconds = current - trace['started']
            if seconds < 0:
                return False
            trace['acknowledged'] = True
        return self.record('capture_request_to_broker_ack', seconds)
