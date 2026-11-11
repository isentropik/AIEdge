import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from decimal import Decimal as D
from types import SimpleNamespace
from unittest.mock import patch
from datetime import timezone
from reviewed_photo import load, constraints, NAME
from daily_constraints import Budget, WorkLimit
from daily_empirical import refine
from image_retention import ImageRetention
import test_daily_constraints as constraint_fixture
import test_daily_empirical as empirical_fixture


class PhotoTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'images').mkdir()
        self.db=sqlite3.connect(self.root/'captures.sqlite3');self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE capture_events(event_id INTEGER,camera TEXT,frame_id TEXT);
          CREATE TABLE frames(camera TEXT,frame_id TEXT,sha256 TEXT,captured_at TEXT);
          CREATE TABLE capture_clocks(camera TEXT,frame_id TEXT,clock_id TEXT,monotonic_us INTEGER);''')
        image=b'explicitly reviewed synthetic fixture';self.sha=hashlib.sha256(image).hexdigest()
        (self.root/'images'/(self.sha+'.jpg')).write_bytes(image)
        self.review=dict(review_id='test-downward-sector',event_id=2,camera='saved',source_sha256=self.sha,
          captured_at='2026-11-07T00:00:15+00:00',clock_id='c'*32,monotonic_us=115000000,
          format_id='b'*64,pipeline_id='a'*64,phase_lower_ft3='1.875',phase_upper_ft3='3.125')
        self.save()
        self.db.execute('INSERT INTO capture_events VALUES(2,?,?)',('saved','frame'))
        self.db.execute('INSERT INTO frames VALUES(?,?,?,?)',('saved','frame',self.sha,self.review['captured_at']))
        self.db.execute('INSERT INTO capture_clocks VALUES(?,?,?,?)',('saved','frame','c'*32,115000000))
        self.db.commit();self.db.execute('PRAGMA query_only=ON')
        f=constraint_fixture.DailyConstraintsTests()
        self.rows=[f.row(1,0,[(102.5,102.6),(107.5,107.6)]),f.row(3,23,[(102.5,102.6),(107.5,107.6),(112.5,112.6)])]
        for r in self.rows:r['event_observation'].update(format_id='b'*64,clock_id='c'*32)
        self.doc=dict(f.document,dials=[dict(value_per_revolution=n) for n in (10000000,1000000,100000,10000,1000,5)])
        self.policy=dict(capacity_cfh=775,format_id='b'*64,pipeline_id='a'*64)
    def save(self):
        (self.root/NAME).write_text(json.dumps(dict(schema_version=1,reviews=[self.review])),encoding='utf-8')
    def calculate(self):return constraints(self.db,self.rows,self.doc,self.policy,Budget())
    def test_intermediate_photo_excludes_extra_turn_without_changing_rows(self):
        before=copy.deepcopy(self.rows);changes=self.db.total_changes
        edges,used=self.calculate()
        self.assertEqual(edges,[(1,3,D(0),D('.1'))]);self.assertEqual(used[0]['event_id'],2)
        self.assertEqual(before,self.rows);self.assertEqual(changes,self.db.total_changes)
        self.assertTrue(all(r['delta'] is None for r in self.rows))
    def test_all_absolute_bands_preserved(self):
        self.rows[0]['absolute']['bounds']['ranges'].append(dict(lower='112.5',upper='112.6'))
        self.assertEqual(self.calculate()[0][0][3],D('.1'))
    def test_full_circle_does_not_rule_out_turn(self):
        self.review.update(phase_lower_ft3='0',phase_upper_ft3='5');self.save()
        self.assertGreater(self.calculate()[0][0][3],D('4.9'))
    def test_missing_image_rejects_review(self):
        (self.root/'images'/(self.sha+'.jpg')).unlink()
        with self.assertRaises(OSError):self.calculate()
    def test_tampered_image_rejects_review(self):
        (self.root/'images'/(self.sha+'.jpg')).write_bytes(b'changed')
        with self.assertRaises(ValueError):self.calculate()
    def test_acquisition_binding_checks_every_source_field(self):
        original=copy.deepcopy(self.review)
        for k,v in [('camera','other'),('source_sha256','d'*64),('clock_id','d'*32),
                    ('captured_at','2026-11-07T00:00:16+00:00'),('monotonic_us',116000000),
                    ('format_id','d'*64),('pipeline_id','d'*64)]:
            self.review=dict(original,**{k:v});self.save()
            with self.subTest(field=k),self.assertRaises(ValueError):self.calculate()
    def test_absent_manifest_disabled(self):
        (self.root/NAME).unlink();self.assertEqual(self.calculate(),([],[]))
    def test_outside_period_not_applied(self):
        self.review['event_id']=4;self.save();self.assertEqual(self.calculate(),([],[]))
    def test_long_gap_not_projected(self):
        self.rows[1]['event_observation']['monotonic_us']+=60000000
        self.assertEqual(self.calculate(),([],[]))
    def test_manifest_is_bounded_and_unique(self):
        for doc in ({'schema_version':1,'reviews':[self.review]*9},
                    {'schema_version':1,'reviews':[self.review]*2},
                    {'schema_version':True,'reviews':[self.review]}):
            (self.root/NAME).write_text(json.dumps(doc))
            with self.assertRaises(ValueError):load(self.root)
        (self.root/NAME).write_text('{"schema_version":1,"schema_version":1,"reviews":[]}')
        with self.assertRaises(ValueError):load(self.root)
    def test_invalid_values_fail_closed(self):
        original=copy.deepcopy(self.review)
        for k,v in [('event_id',True),('phase_lower_ft3','NaN'),('phase_upper_ft3',6),
                    ('review_id','../unsafe'),('captured_at','2026-11-07'),('clock_id','bad')]:
            self.review=dict(original,**{k:v});self.save()
            with self.subTest(field=k),self.assertRaises(ValueError):load(self.root)
    def test_review_photo_pinned_outside_ordinary_budget(self):
        retention=ImageRetention(SimpleNamespace(root=self.root),None)
        self.assertIn(self.sha,retention.pins())
        (self.root/NAME).write_text('{bad')
        with self.assertRaises(ValueError):retention.pins()
    def test_geometry_change_rejected(self):
        self.doc['dials'][-1]['value_per_revolution']=10
        with self.assertRaises(ValueError):self.calculate()
    def test_contradictory_review_rejected(self):
        self.review.update(phase_lower_ft3='0',phase_upper_ft3='0');self.save()
        with self.assertRaises(ValueError):self.calculate()


class IndependentBudgetTests(unittest.TestCase):
    def test_elapsed_exhaustion_does_not_discard_daily(self):
        f=empirical_fixture.DailyEmpiricalTests();f.setUp();bounded=dict(f.base,lower='2.00',upper='2.00')
        with patch('daily_empirical.interval_edges',return_value=[(1,3,D(0),D(12))]), \
             patch('reviewed_photo.constraints',return_value=([],[])), \
             patch('daily_empirical._tighten',side_effect=[WorkLimit,bounded]):
            r=refine(None,f.rows,f.f.day,timezone.utc,f.doc,f.base,f.policy)
        self.assertTrue(r['empirical_constraints_applied']);self.assertEqual(r['lower'],'2.00')
        self.assertIsNone(r['elapsed_range']);self.assertEqual(r['elapsed_unavailable_reason'],'work_limit')
    def test_daily_exhaustion_keeps_completed_elapsed_and_no_photo_claim(self):
        f=empirical_fixture.DailyEmpiricalTests();f.setUp();bounded=dict(f.base,lower='2.00',upper='2.00')
        with patch('daily_empirical.interval_edges',return_value=[(1,3,D(0),D(12))]), \
             patch('reviewed_photo.constraints',return_value=([],[{'review_id':'r'}])), \
             patch('daily_empirical._tighten',side_effect=[bounded,WorkLimit]):
            r=refine(None,f.rows,f.f.day,timezone.utc,f.doc,f.base,f.policy)
        self.assertEqual(r['elapsed_range']['lower'],'2.00');self.assertEqual(r['upper'],'12.00')
        self.assertEqual(r['reviewed_photo_constraints'],[])
    def test_invalid_photo_keeps_supported_daily_without_its_constraint(self):
        f=empirical_fixture.DailyEmpiricalTests();f.setUp()
        with patch('daily_empirical.interval_edges',return_value=[(1,3,D(0),D(12))]), \
             patch('reviewed_photo.constraints',side_effect=ValueError('bad source')):
            r=refine(None,f.rows,f.f.day,timezone.utc,f.doc,f.base,f.policy)
        self.assertTrue(r['empirical_constraints_applied']);self.assertEqual(r['reviewed_photo_evidence_state'],'unavailable')
        self.assertEqual(r['reviewed_photo_constraints'],[])

if __name__=='__main__':unittest.main()

