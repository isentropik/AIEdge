import json
import unittest
from unittest.mock import patch
from test_image_retention import ImageRetentionTests
from gap_images import gap_pairs,older_keep

class GapEvidenceTests(unittest.TestCase):
    def setUp(self):
        ImageRetentionTests.setUp(self)
        self.dev.stop()
        self.dev=patch('image_retention.DEVELOPMENT_IMAGES',4);self.dev.start();self.addCleanup(self.dev.stop)
        self.images=list(self.blobs)
    def fail_after(self,event):
        with self.store.connect() as db:db.execute("INSERT INTO capture_failure_boundaries VALUES(?,?,'timeout','unknown')",(event,event))
    def records(self,values):
        with self.store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS consumption_records(segment_id TEXT,event_id INTEGER,result TEXT,PRIMARY KEY(segment_id,event_id))')
            db.executemany('INSERT INTO consumption_records VALUES(?,?,?)',[(s,e,json.dumps(v)) for s,e,v in values])
    def select(self,eligible,pinned=set(),slots=2,byte_limit=64*1024*1024):
        report={}
        with self.store.connect() as db:keep=older_keep(db,eligible,pinned,slots,byte_limit,report)
        return keep,report
    def test_missing_mate_never_spends_slot_on_orphan(self):
        self.fail_after(7)
        keep,report=self.select({self.images[6]})
        self.assertEqual(keep,set());self.assertEqual(report['missing_endpoint_pairs'],1)
        self.assertFalse(report['coverage_complete'])
    def test_missing_mate_does_not_displace_older_complete_pair(self):
        self.fail_after(2);self.fail_after(7)
        keep,_=self.select({self.images[1],self.images[2],self.images[6]})
        self.assertEqual(keep,set(self.images[1:3]))
    def test_other_segment_acceptance_cannot_hide_rejected_bracket(self):
        self.records([('a',1,{'observation_accepted':True}),('a',2,{'observation_accepted':False}),('a',3,{'observation_accepted':True}),('b',2,{'observation_accepted':True})])
        with self.store.connect() as db:self.assertIn((self.images[0],self.images[2]),gap_pairs(db))
    def test_short_ambiguous_interval_preserves_both_sides(self):
        self.records([('a',6,{'observation_accepted':True,'state':'bounded'}),('a',7,{'observation_accepted':True,'state':'ambiguous'})])
        with patch('image_retention.DEVELOPMENT_IMAGES',2):self.worker.sweep()
        for s in self.images[5:7]:self.assertTrue((self.root/'images'/(s+'.jpg')).exists())
    def test_unbounded_transition_is_evidence_even_at_short_interval(self):
        self.records([('a',6,{'observation_accepted':True,'upper_unbounded':False}),('a',7,{'observation_accepted':True,'upper_unbounded':True})])
        with self.store.connect() as db:self.assertIn(tuple(self.images[5:7]),gap_pairs(db))
    def test_continuing_ambiguity_does_not_pin_every_frame(self):
        self.records([('a',e,{'observation_accepted':True,'state':'bounded' if e==6 else 'ambiguous'}) for e in range(6,10)])
        with self.store.connect() as db:
            pairs=gap_pairs(db);self.assertIn(tuple(self.images[5:7]),pairs)
            self.assertNotIn(tuple(self.images[6:8]),pairs)
    def test_two_complete_pairs_report_budget_loss_honestly(self):
        self.fail_after(2);self.fail_after(7)
        keep,report=self.select(set(self.images),slots=2)
        self.assertEqual(keep,set(self.images[6:8]));self.assertEqual(report['complete_pairs'],1)
        self.assertEqual(report['budget_excluded_pairs'],1);self.assertFalse(report['coverage_complete'])
    def test_recent_side_pays_only_for_older_mate(self):
        self.fail_after(7)
        keep,report=self.select({self.images[6]},{self.images[7]},slots=1,byte_limit=5)
        self.assertEqual(keep,{self.images[6]});self.assertTrue(report['coverage_complete'])
    def test_oversize_pair_not_half_saved(self):
        self.fail_after(7)
        keep,report=self.select(set(self.images[6:8]),byte_limit=9)
        self.assertEqual(keep,set());self.assertEqual(report['budget_excluded_pairs'],1)
    def test_missing_physical_file_is_not_reported_as_saved(self):
        self.fail_after(7);(self.root/'images'/(self.images[7]+'.jpg')).unlink()
        report={}
        with self.store.connect() as db:self.worker._candidates(db,10,report)
        self.assertEqual(report['complete_pairs'],0);self.assertEqual(report['missing_endpoint_pairs'],1)
    def test_new_ambiguity_after_delete_intent_cancels_unlink(self):
        cutoff,candidates=self.worker.candidates();image=candidates[0];event=self.blobs[image][0]
        self.worker.retire([image],cutoff)
        self.records([('a',event,{'observation_accepted':True,'state':'bounded'}),('a',event+1,{'observation_accepted':True,'state':'ambiguous'})])
        self.worker.finish_pending();self.assertTrue((self.root/'images'/(image+'.jpg')).exists())
    def test_audit_exposed_with_timestamp_and_unchanged_ledger(self):
        self.fail_after(7)
        with self.store.connect() as db:before=db.execute('SELECT * FROM capture_failure_boundaries').fetchall()
        self.worker.sweep();status=self.store.status()
        self.assertTrue(status['retention_evidence']['checked_at']);self.assertEqual(status['retention_evidence']['complete_pairs'],1)
        with self.store.connect() as db:self.assertEqual(before,db.execute('SELECT * FROM capture_failure_boundaries').fetchall())
    def test_open_gap_is_not_reported_as_two_sided_coverage(self):
        self.fail_after(12)
        keep,report=self.select(set(),{self.images[11]},slots=0)
        self.assertEqual(report['awaiting_right_endpoint'],1)
        self.assertEqual(report['awaiting_right_left_retained'],1)
        self.assertEqual(report['complete_pairs'],0)
        self.assertFalse(report['coverage_complete'])

    def test_shared_digest_closed_pair_is_not_an_open_gap(self):
        self.fail_after(7)
        with self.store.connect() as db:db.execute("UPDATE frames SET sha256=? WHERE frame_id='8'",(self.images[6],))
        _,report=self.select({self.images[6]},slots=1)
        self.assertEqual(report['awaiting_right_endpoint'],0)
        self.assertEqual(report['complete_pairs'],1)
        self.assertTrue(report['coverage_complete'])
