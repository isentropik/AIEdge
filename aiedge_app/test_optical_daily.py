"""The fine dial may support usage on a day whose absolute register cannot be read."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
import sqlite3
import tempfile
import unittest
import json
from unittest.mock import patch

from nominal_daily import NominalPublisher
from optical_daily import endpoint
from reading_format import validate


ZONE = 'UTC'
MIDNIGHT = datetime(2026, 11, 22, tzinfo=timezone.utc)
DOC, FMT = validate(dict(version=1, pipeline_id='a'*64, unit='ft3', maximum_rate_per_second=.5,
                         dials=[dict(index=i,value_per_revolution=q,position_error=.1)
                                for i,q in enumerate((10000,1000,5))]))


class Output:
    base = 'test'
    interval = 6
    config = {'unique_id':'test-meter'}

    def __init__(self):
        self.messages = []

    def _publish(self, topic, payload, retained):
        self.messages.append((topic, payload, retained))


class OpticalDailyTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('CREATE TABLE capture_events(event_id INTEGER PRIMARY KEY,camera,frame_id);'
                              'CREATE TABLE frames(camera,frame_id,captured_at,sha256);'
                              'CREATE TABLE consumption_segment_links(first_event);'
                              'CREATE TABLE capture_failure_boundaries(after_event_id);')
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.checkpoint = Path(tmp.name)/'checkpoint.db'
        self.output = Output()
        self.worker = NominalPublisher(self.checkpoint)
        self.phases = {}
        def read(db, start, end, doc, src, same_clock=True):
            return {e: item for e, item in self.phases.items() if start <= e <= end
                    and item[0]['camera'] == src['camera'] and item[0]['format_id'] == src['format_id']
                    and (not same_clock or item[0]['clock_id'] == src['clock_id'])}
        replacement = patch('optical_daily.phases', read)
        replacement.start()
        self.addCleanup(replacement.stop)

    @contextmanager
    def connect(self):
        yield self.db

    def frame(self, event, value, *, seconds=None, context='ctx', clock='boot', tick=None, observed=True):
        seconds = event*6 if seconds is None else seconds
        stamp = (MIDNIGHT + timedelta(seconds=seconds)).isoformat()
        src = dict(camera='meter',captured_at=stamp,source_sha256=format(event,'064x'),event_id=event,
                   context_id=context,clock_id=clock,monotonic_us=int(seconds*1000000) if tick is None else tick,
                   format_id=FMT,request_sha256=format(event+1,'064x'))
        self.db.execute('INSERT INTO capture_events VALUES(?,?,?)',(event,'meter',event))
        self.db.execute('INSERT INTO frames VALUES(?,?,?,?)',('meter',event,stamp,src['source_sha256']))
        if observed:
            mid = D(str(value))
            self.phases[event] = src,(mid-D('.05'),mid+D('.05'))
        c = dict(event_id=event, segment_id='seg', observation_context=context, format_id=FMT,
                 observation_accepted=False,reason='consumption_positions_contradict_bounds',
                 source_sha256=src['source_sha256'],event_observation=src)
        reading = dict(state='inconsistent', reason='dial_bounds_disagree', format_id=FMT,source_sha256=src['source_sha256'],
                       consistency={'state':'inconsistent','dial_indices':[0,1]})
        return dict(_timing_event_id=event,_publication_segment_id='seg',consumption=c,format=DOC,
                    latest={'sha256':src['source_sha256'],'captured_at':stamp},_raw_meter_reading=reading)

    def publish(self, snap, full=None, obs=None):
        now = datetime.fromisoformat(snap['latest']['captured_at'])
        class Fixed(datetime):
            @classmethod
            def now(cls,tz=None):
                return now.astimezone(tz)
        with patch('nominal_daily.datetime', Fixed):
            self.worker.publish(self.output,obs,full,now.date(),ZONE,store=self,snapshot=snap)
        return self.worker.record['state']

    def test_replay_starts_after_midnight_and_publishes_proven_crossing_once(self):
        self.frame(1,1,seconds=-5400)
        self.db.execute('INSERT INTO capture_failure_boundaries VALUES(1)')
        self.frame(2,4.7,seconds=3600)
        last=self.frame(3,.2,seconds=3606)
        state=self.publish(last)
        self.assertEqual((state['value_ft3'], state['status'], state['lower_ft3'],state['upper_ft3']),
                         ('0.40','partial_coverage',None,None))
        self.assertEqual(state['coverage_started_at'],self.phases[2][0]['captured_at'])
        self.assertEqual((state['event_id'],state['measured_at'],state['source_sha256']),
                         (3,last['latest']['captured_at'],last['latest']['sha256']))
        self.assertEqual(self.worker.record['movement']['points'][0][2],2)
        self.assertEqual(self.publish(last),state)
        self.assertEqual(len(self.output.messages),1)
        self.worker=NominalPublisher(self.checkpoint)
        self.assertEqual(self.publish(last),state)
        self.assertEqual(self.db.execute('SELECT * FROM capture_failure_boundaries').fetchall(),[(1,)])

    def test_rate_limit_is_only_a_bound_and_jitter_earns_nothing(self):
        self.frame(1,1)
        self.frame(2,.99,seconds=18)
        third=self.frame(3,1.04,seconds=30)
        self.assertEqual(self.publish(third)['value_ft3'],'0.00')
        self.assertEqual(self.publish(self.frame(4,1.5,seconds=42))['value_ft3'],'0.40')
        self.assertEqual(self.publish(self.frame(5,1.2,seconds=54))['value_ft3'],'0.40')
        self.assertTrue(self.worker.record['movement']['dial_gaps'])

    def test_failed_missing_and_changed_source_frames_cannot_add_usage(self):
        self.frame(1,1)
        self.frame(2,1.3)
        self.db.execute('INSERT INTO capture_failure_boundaries VALUES(2)')
        self.frame(3,3)
        self.frame(4,3.2)
        self.frame(5,.9,observed=False)
        self.frame(6,1.8)
        self.frame(7,3,context='another')
        self.frame(8,4,context='another',clock='boot-b')
        self.frame(9,4.2,context='another',clock='boot-b',tick=1000000)
        self.db.execute('INSERT INTO consumption_segment_links VALUES(10)')
        s=self.publish(self.frame(10,.2,context='another',clock='boot-b'))
        self.assertEqual(s['value_ft3'],'0.30')
        self.assertGreaterEqual(len(self.worker.record['movement']['dial_gaps']),2)
        self.assertEqual(s['event_id'],10)

    def test_invalid_endpoint_fine_conflict_and_expired_evidence_stay_unmeasured(self):
        snap=self.frame(1,3)
        now=datetime.fromisoformat(snap['latest']['captured_at'])
        self.assertIsNone(endpoint(snap,None,False,now+timedelta(seconds=91),90))
        snap['_raw_meter_reading']['consistency']['dial_indices']=[1,2]
        self.assertIsNone(self.publish(snap)['event_id'])
        snap['_raw_meter_reading']['consistency']['dial_indices']=[0,1]
        snap['consumption']['event_observation']['request_sha256']='wrong'
        # A mismatched saved request cannot lend its timestamp to the nominal.
        src,band=self.phases[1];self.phases[1]=dict(src,request_sha256='saved'),band
        self.assertIsNone(self.publish(snap)['event_id'])
        snap['_raw_meter_reading']['source_sha256']='0'*64
        self.assertIsNone(endpoint(snap,None,False,now,90))

    def test_bounds_and_accepted_register_return_have_separate_authority(self):
        one=self.frame(1,2);self.publish(one)
        full=dict(day=MIDNIGHT.date().isoformat(),timezone=ZONE,through=self.phases[1][0],
                  lower='12.4',upper='34.5',low_use_estimate={'value_ft3':'13.00'})
        two=self.frame(2,2.5)
        s=self.publish(two,full,obs=self.phases[2][0])
        self.assertEqual((s['value_ft3'],s['lower_ft3'],s['upper_ft3'],s['bounds_event_id'],s['event_id']),
                         ('0.40',12.4,34.5,1,2))
        self.assertEqual(s['bounds_measured_at'],one['latest']['captured_at'])
        two['consumption']=None
        self.assertEqual(self.publish(two)['value_ft3'],'0.40')
        self.assertEqual(self.worker.record['state']['status'],'held_at_last_reading')
        nextday=self.frame(3,3.2,seconds=86400+2)
        tomorrow=self.publish(nextday)
        self.assertEqual((tomorrow['value_ft3'],tomorrow['event_id'],tomorrow['lower_ft3']),('0.00',3,None))

    def test_tiny_replay_pages_resume_after_restart_without_skipping_data(self):
        self.frame(1,4.7);self.frame(2,.2);self.frame(3,.5)
        end=self.frame(4,.8)
        with patch('optical_daily.PAGE',2):
            first=self.publish(end)
            self.assertEqual((first['event_id'],first['value_ft3']),(2,'0.40'))
            self.worker=NominalPublisher(self.checkpoint)
            last=self.publish(end)
            self.assertEqual((last['event_id'],last['value_ft3']),(4,'1.00'))

    def test_mqtt_worker_and_overview_publish_same_partial_source_while_register_is_rejected(self):
        from daily_mqtt import DailyPublisher
        from test_mqtt_consumption import ConsumptionPublicationTests
        worker = ConsumptionPublicationTests().worker(str(self.checkpoint.parent))
        self.addCleanup(worker.close)
        worker.daily = DailyPublisher(self)
        self.frame(1, 1)
        snap = self.frame(2, 1.5)
        snap['reading'] = {'state':'unavailable','value':None}
        snap['consumption']['unresolved_gap'] = {'first_event':1,'delta':None}
        now = datetime.fromisoformat(snap['latest']['captured_at'])
        class Fixed(datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz)
        with patch.dict('os.environ', TZ='UTC'), patch('nominal_daily.datetime',Fixed), patch('mqtt_output.datetime',Fixed):
            worker.publish_snapshot(snap)
        self.assertIsNone(worker.nominal_error)
        data = [json.loads(msg[1]) for msg in worker.client.sent if msg[0].endswith('/daily_nominal')]
        self.assertEqual(len(data), 1)
        daily, = data
        self.assertEqual((daily['event_id'],daily['value_ft3'],daily['lower_ft3'],daily['upper_ft3']), (2,'0.40',None,None))
        usage = worker.status()['usage']
        self.assertEqual((usage['daily_nominal'],usage['movement_history']['points'][-1][2]), (daily,2))
        self.assertIsNone(snap['consumption']['unresolved_gap']['delta'])
        self.assertFalse(any(json.loads(msg[1]).get('label') for msg in worker.client.sent if msg[0].endswith('/daily_range')))
