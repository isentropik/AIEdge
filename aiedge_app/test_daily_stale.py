"""Exercise both MQTT topics using incompatible saved dial positions."""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, Mock, patch

import daily_mqtt
from daily_constraints import InconsistentConstraints
from nominal_daily import NominalPublisher
from published_usage import snapshot


class DailyStaleTests(TestCase):
    def setUp(self):
        import test_daily_turn_recovery as fixtures
        fixture = fixtures.DailyTurnRecoveryTests()
        self.rows = fixture.rows()
        self.rows[-1].update(minimum=1,maximum=1)
        for row in self.rows:
            row['event_observation']['source_sha256'] = str(row['event_id'])*64
        self.doc = fixture.format
        self.day = fixture.day
        self.wall = fixture.midnight+timedelta(minutes=1)
        self.clock = 1000
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = MagicMock()
        self.store.connect.return_value.__enter__.return_value.execute.return_value=[('c','p','f',1)]
        self.output = Mock(base='meter', interval=30, config={'unique_id':'meter','device':{}})
        self.restart()
        for stub in (patch.dict('os.environ', TZ='UTC'),
                     patch('daily_mqtt.time.monotonic',side_effect=lambda:self.clock)):
            stub.start();self.addCleanup(stub.stop)

    def restart(self):
        self.pub = daily_mqtt.DailyPublisher(self.store,checkpoint=self.root/'source.json')
        self.nom = NominalPublisher(self.root/'nom.sqlite3')

    def publish(self, rows, **obs_changes):
        self.clock += 301
        row = rows[-1]
        obs = dict(row['event_observation'],segment_id=row['segment_id'],segment_started_at=row['anchor_captured_at'],
                   minimum=row['minimum'],maximum=row['maximum'])
        obs.update(obs_changes)
        with (patch('daily_mqtt.daily_records',return_value=iter(rows)),
              patch('daily_mqtt.fresh_range',return_value=obs),patch('daily_mqtt.datetime',wraps=datetime) as clock):
            clock.now.return_value = self.wall
            self.pub.publish(self.output,{'format':self.doc,'_publication_segment_id':row['segment_id']})
        payload = self.pub.last_good[0] if self.pub.last_good else None
        self.nom.publish(self.output,obs,payload,self.day,'UTC')
        return payload,self.nom.record['state']

    def test_two_topics_hold_original_bounds_and_source(self):
        initial,n=self.publish(self.rows[:-1])
        original=copy.deepcopy(self.rows)
        stale,s=self.publish(self.rows)
        self.assertEqual(stale['status'],s['status'])
        self.assertEqual(s['status'],'stale')
        for key in ('before','after','through','lower','upper','nominal_estimate'):
            self.assertEqual(stale[key],initial[key])
        for key in ('event_id','measured_at','source_sha256','value_ft3','lower_ft3','upper_ft3'):
            self.assertEqual(s[key],n[key])
        self.assertEqual(stale['conflict_event_id'],4)
        self.assertEqual(stale['checked_through'],self.rows[-1]['event_observation'])
        self.assertEqual(self.rows,original)
        self.assertEqual(json.loads(self.output._publish.call_args.args[1]),s)

    def test_upgrade_after_conflict_recovers_unpublished_prefix(self):
        p,s=self.publish(self.rows)
        self.assertEqual((p['through']['event_id'],s['event_id'],s['status']),(3,3,'stale'))

    def test_restarts_and_pending_observations_keep_stale_time(self):
        p,s=self.publish(self.rows)
        self.restart()
        self.nom.publish(self.output,None,None,self.day,'UTC')
        self.assertEqual(self.nom.record['state'],s)
        self.assertEqual(self.publish(self.rows),(p,s))

    def test_later_supported_reading_clears_stale(self):
        self.publish(self.rows)
        # Model the next qualified lineage. The saved conflicting record stays intact.
        next_row=copy.deepcopy(self.rows[-1])
        stamp=(self.wall+timedelta(seconds=10)).isoformat()
        next_row.update(event_id=5,segment_id='new',minimum=0,maximum=0,
                        observation_full_anchor_event_id=5,anchor_captured_at=stamp)
        next_row['event_observation'].update(event_id=5,source_sha256='5'*64,captured_at=stamp,monotonic_us=72000000)
        newer=self.rows[:-1]+[next_row]
        full,s=self.publish(newer)
        self.assertEqual((s['event_id'],s['status']),(5,'daily_range'))
        self.assertNotIn('conflict_event_id',s)
        self.assertNotIn('status',full)

    def test_an_unrelated_series_does_not_inherit_stale_usage(self):
        self.publish(self.rows)
        obs=dict(self.rows[-1]['event_observation'],format_id='other',segment_id='other',
                 segment_started_at=self.rows[-1]['event_observation']['captured_at'],minimum=0,maximum=0)
        self.nom.publish(self.output,obs,None,self.day,'UTC')
        self.assertEqual(self.nom.record['state']['status'],'partial_coverage')
        self.assertIsNone(self.nom.record['state']['lower_ft3'])

    def test_missing_bracket_cannot_manufacture_full_day(self):
        self.assertIsNone(self.publish(self.rows[1:])[0])
        self.assertNotEqual(self.nom.record['state']['status'],'stale')

    def test_new_clock_or_bad_source_cannot_claim_prior_day(self):
        self.publish(self.rows[:-1])
        bad=copy.deepcopy(self.rows)
        bad[-1]['event_observation']['clock_id']='other'
        self.assertIsNone(self.publish(bad)[0])
        self.assertIsNone(self.publish(self.rows,source_sha256='a'*64)[0])

    def test_generic_conflict_revalidates_saved_source_after_restart(self):
        good,_=self.publish(self.rows[:-1])
        self.restart()
        original=daily_mqtt.daily_range
        def global_conflict(rows,*args,**kwargs):
            if len(rows)==4:raise InconsistentConstraints('conflicting day')
            return original(rows,*args,**kwargs)
        with patch('daily_mqtt.daily_range',side_effect=global_conflict):
            stale,_=self.publish(self.rows)
            self.assertEqual(stale['through'],good['through'])
            changed=copy.deepcopy(self.rows)
            changed[-2]['event_observation']['source_sha256']='e'*64
            self.assertIsNone(self.publish(changed)[0])

    def test_older_display_time_survives_status_freshness_checks(self):
        p,s=self.publish(self.rows)
        self.assertEqual(snapshot(self.pub,now=self.clock,wall=self.wall+timedelta(hours=3))['daily'],p)
        self.assertNotIn('daily',snapshot(self.pub,now=self.clock+700,wall=self.wall))
        self.assertNotIn('daily',snapshot(self.pub,now=self.clock,wall=self.wall+timedelta(days=1)))

    def test_midnight_resets_the_nominal_checkpoint(self):
        self.publish(self.rows)
        self.nom.publish(self.output,None,None,self.day+timedelta(days=1),'UTC')
        self.assertEqual(self.nom.record['state']['status'],'opening_balance')
        self.assertIsNone(self.nom.record['state']['measured_at'])

    def test_corrupt_checkpoint_is_rebuilt_from_the_ledger(self):
        self.publish(self.rows[:-1])
        path=self.root/'source.json'
        document=json.loads(path.read_text())
        document['source']['upper']='999999'
        path.write_text(json.dumps(document))
        self.restart()
        self.assertIsNone(self.pub.supported_source)
        full,nominal=self.publish(self.rows)
        self.assertEqual(nominal['status'],'stale')
        self.assertNotEqual(full['upper'],'999999')

    def test_checkpoint_io_failure_keeps_the_qualified_range(self):
        with patch('setup_store.Setup._atomic',side_effect=OSError('read only')),self.assertLogs('daily_mqtt',level='WARNING'):
            full,nominal=self.publish(self.rows)
        self.assertEqual(full['status'],nominal['status'])
        self.assertEqual(self.pub.supported_source['through'],full['through'])

    def test_restart_reuses_acknowledged_bounds_when_recalculation_conflicts(self):
        original,state=self.publish(self.rows[:-1])
        self.restart()
        with patch('daily_mqtt.daily_range',side_effect=InconsistentConstraints('day conflicts')) as calc:
            held,nom=self.publish(self.rows)
        self.assertEqual(calc.call_count,1)
        self.assertEqual(held['through'],original['through'])
        self.assertEqual((nom['lower_ft3'],nom['upper_ft3'],nom['value_ft3']),
                         (state['lower_ft3'],state['upper_ft3'],state['value_ft3']))

    def test_later_source_change_cannot_hide_behind_an_earlier_conflict(self):
        self.publish(self.rows[:-1])
        bad=copy.deepcopy(self.rows)
        later=copy.deepcopy(bad[-1])
        later['event_id']=5
        later['event_observation'].update(event_id=5,clock_id='different')
        bad.append(later)
        with patch('daily_mqtt.daily_range',side_effect=daily_mqtt.ReadingConflict('conflict',4)):
            self.assertIsNone(self.publish(bad)[0])
