from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from threading import Thread
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from register_history import snapshot
from service import handler


class RegisterHistoryTests(unittest.TestCase):
    # Cross the 25-hour day on which Pacific daylight saving time ends.
    now = datetime.fromisoformat('2026-11-02T10:00:00-08:00')
    mqtt = dict(overview_timezone='America/Los_Angeles',usage={'absolute_nominal':{
        'measured_at':'2026-11-02T08:30:00-08:00','value_ft3':'260040.2'}})
    rows = [
        dict(end='2026-10-31T07:00:00Z',state=260010, sum=12),
        dict(end='2026-11-02T08:00:00Z',state=260030, sum=32),
        dict(end='2026-11-03T08:00:00Z',state=260033, sum=35),
    ]

    def test_daily_states_missing_days_and_latest_at_its_own_time(self):
        data = snapshot('sensor.gas',self.mqtt,7,now=self.now,fetch=lambda *_:self.rows)
        self.assertEqual(data['start'],'2026-10-27')
        self.assertEqual([p['day'] for p in data['points']],['2026-10-30','2026-11-01','2026-11-02'])
        self.assertEqual([p['value'] for p in data['points']],[260010,260030,260040.2])
        self.assertEqual(data['points'][-1]['at'],self.mqtt['usage']['absolute_nominal']['measured_at'])

    def test_stale_reading_and_partial_statistics_do_not_fill_today(self):
        for ts in ('2026-11-01T08:30:00-08:00','2026-11-03T08:30:00-08:00','invalid'):
            data=snapshot('sensor.gas',dict(self.mqtt,usage={'absolute_nominal':{
                'measured_at':ts,'value_ft3':260000}}),28,now=self.now,fetch=lambda *_:self.rows)
            self.assertTrue(all(p['kind']=='close' and p['day']<data['today'] for p in data['points']))

    def test_past_window_uses_local_day_boundaries(self):
        requests=[]
        def fetch(entity,start,stop):
            requests.append((entity,start,stop))
            return self.rows
        data=snapshot('sensor.gas',self.mqtt,7,date(2026,11,1),now=self.now,fetch=fetch)
        entity,start,stop=requests[0]
        self.assertEqual(entity,'sensor.gas')
        self.assertEqual(stop.astimezone(timezone.utc)-start.astimezone(timezone.utc),timedelta(days=7,hours=1))
        self.assertEqual([p['day'] for p in data['points']],['2026-10-30','2026-11-01'])

    def test_history_http_and_static_asset(self):
        with tempfile.TemporaryDirectory() as folder:
            factory=handler(SimpleNamespace(root=Path(folder)),False,None,
                            mqtt_output=SimpleNamespace(status=lambda:self.mqtt),chart_hours=SimpleNamespace(meter='sensor.gas'))
            with ThreadingHTTPServer(('127.0.0.1',0),factory) as server:
                thread=Thread(target=server.serve_forever,daemon=True)
                thread.start()
                try:
                    def get(route):
                        with closing(HTTPConnection('127.0.0.1',server.server_port,timeout=5)) as conn:
                            conn.request('GET',route)
                            reply=conn.getresponse()
                            return reply.status,reply.read()
                    with patch('register_history.statistics',return_value=[]) as fetch:
                        for days in (7,28,91):
                            status,body=get('/api/register-history?days='+str(days)+'&end=2020-01-10')
                            self.assertEqual(status,200)
                            self.assertEqual(json.loads(body)['points'],[])
                        self.assertEqual(fetch.call_count,3)
                        for args in ('','days=1','days=7&days=28','days=7&end=abc','days=7&other=x'):
                            self.assertEqual(get('/api/register-history?'+args)[0],400)
                        self.assertEqual(fetch.call_count,3)
                    with patch('register_history.statistics',side_effect=OSError('offline')):
                        self.assertEqual(get('/api/register-history?days=7')[0],503)
                    self.assertEqual(get('/register-history.js')[0],200)
                    self.assertIn(b'register-history.js',get('/')[1])
                finally:
                    server.shutdown()
                    thread.join()

    def test_overview_and_container_ship_the_register_chart_together(self):
        root = Path(__file__).parent
        overview = (root / 'index.html').read_text(encoding='utf-8')
        self.assertLess(overview.index('id="register-history-title"'), overview.index('Earlier usage and recovery'))
        self.assertIn('src="register-history.js"', overview)
        for days in (7, 28, 91):
            self.assertIn(f'data-register-days="{days}"', overview)
        packaged = set()
        for line in (root / 'Dockerfile').read_text(encoding='utf-8').splitlines():
            if line.startswith('COPY '):
                packaged.update(line.split()[1:-1])
        self.assertTrue({'register-history.js', 'register_history.py', 'index.html', 'service.py'} <= packaged)
