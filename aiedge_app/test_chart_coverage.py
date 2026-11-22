from datetime import datetime, timedelta, timezone
import sqlite3
from threading import Event
from time import monotonic, sleep
import unittest
from chart_coverage import read_coverage
from gas_trend import GasTrend
from meter_history import millis


class MemoryStore:
    def __init__(self):
        self.db = sqlite3.connect(':memory:')
        self.db.executescript("""
            CREATE TABLE frames(camera, frame_id, captured_at, sha256);
            CREATE TABLE capture_events(event_id INTEGER PRIMARY KEY, camera, frame_id);
            CREATE TABLE capture_failure_boundaries(after_event_id, error);
            CREATE TABLE consumption_segments(format_id, first_event);
        """)

    def connect(self):
        return self.db


class CaptureCoverageTest(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.addCleanup(self.store.db.close)
        self.midnight = datetime(2026, 11, 21, tzinfo=timezone.utc)
        self.sources = {}
        for event, seconds in [(1, 2), (2, 11), (3, 18), (4, 32), (6, 55), (7, 742), (8, 752)]:
            stamp = (self.midnight + timedelta(seconds=seconds)).isoformat()
            self.sources[event] = dict(event_id=event, captured_at=stamp, source_sha256=str(event),
                                       camera='meter', format_id='gas')
            self.store.db.execute('insert into frames values(?,?,?,?)', ('meter', event, stamp, str(event)))
            self.store.db.execute('insert into capture_events values(?,?,?)', (event, 'meter', event))
        self.store.db.commit()
        self.daily = dict(after=self.sources[1], through=self.sources[4], day='2026-11-21', timezone='UTC')
        self.track = dict(midnight=millis(self.midnight), format='gas', points=[[self.ms(8), 12, 8, 5]])

    def ms(self, event):
        return millis(datetime.fromisoformat(self.sources[event]['captured_at']))

    def test_saved_frames_define_gaps_independently_of_publication_ids(self):
        self.store.db.executemany('insert into capture_failure_boundaries values(?,?)',
                                  [(2, 'timeout'), (2, 'connection_failed'), (8, 'future failure')])
        self.store.db.executemany('insert into consumption_segments values(?,?)', [('gas', 4), ('other', 2)])
        old = read_coverage(self.store, self.daily, None)
        full = read_coverage(self.store, self.daily, self.track)
        self.assertEqual(full['gaps'], [[self.ms(a), self.ms(b)] for a,b in [(2,3), (3,4), (4,6), (6,7)]])
        self.assertEqual(full['through'], [8, self.ms(8)])
        self.assertEqual(read_coverage(self.store, self.daily, self.track, old), full)

    def test_unpublished_but_saved_events_are_continuous(self):
        coverage = read_coverage(self.store, self.daily, None)
        self.assertEqual(coverage['gaps'], [])
        self.assertEqual(coverage['first'], [1, self.ms(1)])

    def test_chart_route_updates_coverage_independently_of_recorder(self):
        entered, release = Event(), Event()
        calls = []
        def coverage(daily, track, cached):
            calls.append(cached)
            entered.set()
            release.wait(2)
            stamp, _, event, _ = track['points'][-1]
            return dict(first=[1, self.ms(1)], through=[event, stamp], gaps=[])
        def offline(*args):
            raise OSError('recorder offline')
        cache = GasTrend(fetch=offline, coverage=coverage)
        self.daily['before'] = dict(self.sources[1], event_id=0)
        def read(track):
            return cache.snapshot(self.daily, track)
        def await_event(track, event):
            until = monotonic() + 2
            while monotonic() < until:
                found = read(track).get('capture_coverage')
                if found and found['through'][0] == event:
                    return found
                sleep(.005)
            self.fail('coverage did not advance')
        old = dict(self.track, points=[[self.ms(4), 5, 4, 1]])
        read(old)
        try:
            self.assertTrue(entered.wait(1))
            read(old)
            self.assertEqual(calls, [None])
        finally:
            release.set()
        first = await_event(old, 4)
        await_event(self.track, 8)
        self.assertEqual(calls, [None, first])

    def test_days_endpoints_and_incremental_overlap_are_bound_to_the_source(self):
        bad = {**self.daily, 'through': {**self.sources[4], 'source_sha256': 'other'}}
        for daily,track in [(bad,None), (dict(self.daily, day='2026-11-22'), None),
                            (self.daily,dict(self.track, midnight=0)), (self.daily,dict(self.track, format='water')),
                            (self.daily,dict(self.track, points=[[self.ms(8)+1, 12, 8, 5]]))]:
            with self.subTest(daily=daily, track=track), self.assertRaises(ValueError):
                read_coverage(self.store, daily, track)
        cached = read_coverage(self.store, self.daily, None)
        cached['through'][1] -= 1
        with self.assertRaises(ValueError):
            read_coverage(self.store, self.daily, self.track, cached)
