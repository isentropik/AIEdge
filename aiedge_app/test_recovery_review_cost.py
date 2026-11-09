"""Local synthetic recovery: cost and fail-closed snapshot invariants."""
import unittest,sqlite3
from unittest.mock import patch
import capture_recovery as r
import test_transfer_recovery as fixtures

class RecoveryReviewCostTests(unittest.TestCase):
    setUp=fixtures.TransferRecoveryTests.setUp
    tearDown=fixtures.TransferRecoveryTests.tearDown
    rows=fixtures.TransferRecoveryTests.rows
    failed=fixtures.TransferRecoveryTests.failed
    def test_one_full_review_per_pre_and_post_probe_snapshot(self):
        self.failed()
        old=self.rows('continuous_capture_outcomes')
        with patch.object(r,'continuation_review',wraps=r.continuation_review) as review:
            self.worker.once()
        self.assertEqual(review.call_count,2)
        self.assertEqual(self.camera.calls,2)
        self.assertEqual(self.rows('continuous_capture_outcomes'),old)
        self.worker.once()
        self.assertEqual(self.camera.calls,3)
        with self.store.connect() as db:self.assertTrue(r.boundary(db,2))
    def test_no_per_event_sql_queries(self):
        self.failed();statements=[]
        with self.store.connect() as db:
            db.executemany('INSERT INTO continuous_capture_attempts(rowid,attempt_id,first_event,after_event_id,started_at) VALUES(?,?,1,0,?)', [(-i,'history-'+str(i),'2026-01-01') for i in range(1,101)])
            db.executemany("INSERT INTO continuous_capture_outcomes VALUES(?,'committed',1,NULL,'2026-01-01')", [('history-'+str(i),) for i in range(1,101)])
            db.commit();db.execute('BEGIN')
            db.set_trace_callback(statements.append)
            r.transfer_review(db,1,self.worker.continuation_context(),self.worker.transfer_attempt)
        self.assertEqual(sum('SELECT 1 FROM capture_events WHERE event_id=' in q for q in statements),1) # latest streak only
        self.assertEqual(sum(q=='SELECT event_id FROM capture_events' for q in statements),1)
    def test_historical_missing_event_still_rejected(self):
        self.failed()
        with self.store.connect() as db:db.execute("UPDATE continuous_capture_outcomes SET event_id=999 WHERE outcome='committed'")
        self.worker.once()
        self.assertTrue(self.worker.stop.is_set())
        self.assertEqual(self.rows('capture_continuations'),[])
    def test_historical_metadata_change_during_probe_blocks_acceptance(self):
        self.failed();original=self.camera.readiness
        def probe():
            with self.store.connect() as db:db.execute("UPDATE frames SET received_at='changed'")
            return original()
        self.camera.readiness=probe
        self.worker.once()
        self.assertTrue(self.worker.stop.is_set())
        self.assertEqual(self.rows('capture_continuations'),[])
        self.assertEqual(self.camera.calls,2)
    def test_three_timeouts_preserve_three_unknowns_and_new_request_identity(self):
        from test_transfer_recovery import EVIDENCE
        self.camera.results=iter([True,r.BodyTimeout(EVIDENCE),r.BodyTimeout(EVIDENCE),r.BodyTimeout(EVIDENCE),True])
        self.worker.once()
        for delay in (6,12,24):
            self.worker.once()
            self.assertEqual(self.worker.readiness_retry_delay,delay)
            self.worker.once()
        self.worker.once()
        outcomes=self.rows('continuous_capture_outcomes')
        self.assertEqual([x[1] for x in outcomes],['committed','unknown','unknown','unknown','committed'])
        self.assertEqual(len({x[0] for x in outcomes}),5)
        self.assertEqual(len(self.rows('capture_continuations')),3)
        with self.store.connect() as db:self.assertTrue(r.boundary(db,2))
