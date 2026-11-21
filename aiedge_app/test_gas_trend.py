from copy import deepcopy
from datetime import datetime, timezone
from threading import Event
from time import monotonic, sleep
import unittest
from unittest.mock import patch
from gas_trend import GasTrend, load_day, recorder, series

ENTITY='sensor.test_meter'
def daily(event,minute):
    return dict(day='2026-11-01',timezone='America/Los_Angeles',segment_id='s',lower=event,upper=event+2,label='bounded',
        nominal_estimate={'method':'range_midpoint_v1','value_ft3':event+1},
        before={'source_sha256':'a'*64,'event_id':18,'captured_at':'2026-11-01T06:59:55+00:00'},
        after={'source_sha256':'b'*64,'event_id':19,'captured_at':'2026-11-01T07:00:06+00:00'},through={
            'event_id':event,'source_sha256':format(event,'064x'),'camera':'meter','format_id':'format','context_id':'ctx',
            'clock_id':'clock','captured_at':datetime.fromtimestamp(1793516400+60*minute,timezone.utc).isoformat()})
def row(a):
    return dict(entity_id=ENTITY,state='bounded',attributes=a)

class TrendTests(unittest.TestCase):
    def test_recorder_reads_only_named_entity(self):
        now=datetime.now(timezone.utc)
        with patch('gas_trend.http.client.HTTPConnection') as connect, patch.dict('os.environ',{'SUPERVISOR_TOKEN':'test'}):
            conn=connect.return_value
            conn.getresponse.return_value.status=200
            conn.getresponse.return_value.read.return_value=b'[[]]'
            self.assertEqual(recorder(ENTITY,now,now),[[]])
            connect.assert_called_once_with('supervisor',timeout=12)
            method,route=conn.request.call_args.args
            self.assertEqual(method,'GET')
            self.assertTrue(route.startswith('/core/api/history/period/'))
            self.assertIn('filter_entity_id=sensor.test_meter&',route)
            self.assertEqual(conn.request.call_args.kwargs['headers'],{'Authorization':'Bearer test'})
            conn.close.assert_called_once()
            with self.assertRaises(ValueError):recorder('sensor.foo&other=yes',now,now)
            self.assertEqual(connect.call_count,1)

    def test_same_image_wrong_bracket_and_mismatched_label(self):
        a,b,c=daily(1,1),daily(2,2),daily(3,3)
        b['after']['event_id']=91
        groups=series([[row(a),row(b),dict(row(c),state='different')]],ENTITY,c)['groups']
        self.assertEqual([[p[4] for p in g] for g in groups],[[1]])
        with self.assertRaises(ValueError):series([{}],ENTITY,c)

    def test_dashboard_route_reads_published_history_and_serves_chart(self):
        import json
        from http.server import ThreadingHTTPServer
        from threading import Thread
        from urllib.request import urlopen
        from unittest.mock import Mock
        from service import handler
        store, mqtt, trend = Mock(), Mock(), Mock()
        current=daily(8,8)
        mqtt.status.return_value={'usage':{'daily':current}}
        trend.snapshot.return_value={'status':'ready','groups':[]}
        with ThreadingHTTPServer(('127.0.0.1',0),handler(store,False,None,mqtt_output=mqtt,gas_trend=trend)) as server:
            thread=Thread(target=server.serve_forever,daemon=True)
            thread.start()
            try:
                base='http://127.0.0.1:'+str(server.server_port)
                with urlopen(base+'/api/gas-trend',timeout=3) as response:
                    self.assertEqual(json.load(response),trend.snapshot.return_value)
                    self.assertEqual(response.headers['Cache-Control'],'no-store')
                trend.snapshot.assert_called_once_with(current)
                with urlopen(base+'/gas-charts.js',timeout=3) as response:
                    self.assertIn(b'window.AIEdgeCharts',response.read())
                self.assertEqual(store.method_calls,[])
            finally:
                server.shutdown()
                thread.join()

    def test_gaps_and_source_changes(self):
        a,b,c,d,e,f=[daily(i,i) for i in range(1,7)]
        d['through']['clock_id']='other'
        wrong=deepcopy(e);wrong['before']['source_sha256']='f'*64
        g=daily(7,25)
        rows=[row(a),row(a),row(b),{'entity_id':ENTITY,'state':'unavailable','attributes':{}},
              row(b),row(c),row(d),row(wrong),row(e),row(f),row(g)]
        result=series([rows],ENTITY,g)
        self.assertEqual([[p[4] for p in group] for group in result['groups']],[[1,2],[3],[4],[5,6],[7]])
        self.assertEqual(result['midnight'],1793516400000)
        self.assertEqual(result['groups'][0][0][1:4],[2,1,3])
        self.assertEqual(series([rows],'sensor.other',g)['groups'],[])

    def test_held_values_wrong_day_and_future_measurements(self):
        a,b,c=daily(1,1),daily(2,2),daily(3,3)
        old=deepcopy(b);old['day']='2026-10-31'
        stale=dict(b,status='stale')
        self.assertEqual([p[4] for g in series([[row(a),row(old),row(stale),row(c)]],ENTITY,b)['groups'] for p in g],[1])

    def test_incremental_history_matches_midnight_replay_including_outage(self):
        a,b,c,d=(daily(1,1),daily(2,30),daily(3,31),daily(4,32))
        cache=series([[row(a),row(b)]],ENTITY,b)
        outage=dict(entity_id=ENTITY,state='unavailable',attributes={})
        tail=[row(b),outage,row(c),row(d)]
        full=[[row(a),*tail]]
        with patch('gas_trend.recorder') as fetch:
            fetch.return_value=[tail]
            self.assertEqual(load_day(fetch,ENTITY,d,cache),series(full,ENTITY,d))
            self.assertEqual(fetch.call_count,1)
            self.assertGreater(fetch.call_args.args[1].timestamp()*1000,cache['midnight'])
            fetch.reset_mock()
            fetch.side_effect=[[[row(c),row(d)]],full]
            self.assertEqual(load_day(fetch,ENTITY,d,cache),series(full,ENTITY,d))
            self.assertEqual(fetch.call_count,2)

    def test_concurrent_cache_loading_does_not_block_or_duplicate_fetch(self):
        entered,release=Event(),Event()
        calls=[]
        a=daily(1,1)
        def fetch(entity,start,end):
            calls.append(entity); entered.set();release.wait(2);return [[row(a)]]
        cache=GasTrend(ENTITY,fetch)
        self.assertEqual(cache.snapshot(a)['status'],'loading')
        self.assertTrue(entered.wait(1))
        self.assertEqual(cache.snapshot(a)['status'],'loading')
        release.set()
        until=monotonic()+2
        while cache.snapshot(a)['status']=='loading' and monotonic()<until:sleep(.01)
        self.assertEqual(cache.snapshot(a)['groups'][0][0][4],1)
        self.assertEqual(calls,[ENTITY])
        self.assertEqual(cache.snapshot({})['status'],'no_source')
