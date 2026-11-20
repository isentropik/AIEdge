"""Keep one source-bound positive segment estimate for the native overview."""
import json
import math
import re
from datetime import datetime
from pathlib import Path

from setup_store import Setup


def valid_point(point):
    if not isinstance(point, dict):
        return False
    try:
        measured = datetime.fromisoformat(point['captured_at'])
        start = datetime.fromisoformat(point['segment_started_at'])
        return (measured.tzinfo is not None and start.tzinfo is not None and start <= measured
                and type(point['event_id']) is int and point['event_id'] > 0
                and type(point['value']) in (int, float) and math.isfinite(point['value']) and point['value'] > 0
                and all(isinstance(point[k], str) and re.fullmatch('[0-9a-f]{64}', point[k])
                        for k in ('source_sha256', 'format_id'))
                and isinstance(point['segment_id'], str) and bool(re.fullmatch('[0-9a-f]{32}', point['segment_id'])))
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


class OverviewHistory:
    def __init__(self, directory, instance):
        self.path = Path(directory) / 'overview-segment.json'
        self.instance = instance
        self.point = None
        self.retained = None
        self.save_failed = False
        try:
            with self.path.open('rb') as stream:
                saved = json.loads(stream.read(4097))
            if isinstance(saved, dict) and saved.get('instance') == instance and valid_point(saved.get('point')):
                self.point = saved['point']
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            self.save_failed = True

    def receive(self, topic, payload):
        if len(payload) > 4096:
            return
        try:
            record = json.loads(payload)
        except (ValueError, UnicodeError, RecursionError):
            return
        if not valid_point(record) or datetime.fromisoformat(record['captured_at']) > datetime.now().astimezone():
            return
        prior = self.retained
        if prior and prior[0] == topic and prior[1]['format_id'] == record['format_id'] and (
                record['event_id'] <= prior[1]['event_id'] or
                datetime.fromisoformat(record['captured_at']) < datetime.fromisoformat(prior[1]['captured_at'])):
            return
        self.retained = topic, {k:record[k] for k in ('value', 'event_id', 'captured_at', 'segment_started_at',
                                                      'source_sha256', 'format_id', 'segment_id')}

    def latest(self, topic, revision):
        point = self.point
        if point and point['format_id'] != revision:
            point = None
        retained = self.retained
        if retained and retained[0] == topic and retained[1]['format_id'] == revision:
            other = retained[1]
            if not point or (other['event_id'] > point['event_id'] and
                             datetime.fromisoformat(other['captured_at']) >= datetime.fromisoformat(point['captured_at'])):
                return other
        return point

    def acknowledge(self, point):
        if not valid_point(point):
            return
        prior = self.point
        if prior and (point['event_id'] < prior['event_id'] or
                      (point['event_id'] == prior['event_id'] and (point != prior or not self.save_failed)) or
                      datetime.fromisoformat(point['captured_at']) < datetime.fromisoformat(prior['captured_at'])):
            return
        self.point = dict(point)
        try:
            data = json.dumps({'instance': self.instance, 'point': point}, allow_nan=False).encode('utf-8')
            Setup._atomic(self.path, data)
            self.save_failed = False
        except OSError:
            # Capture and publication can proceed even if the display checkpoint is full.
            self.save_failed = True
