import unittest,random,copy
from decimal import Decimal as D
from unittest.mock import patch
import daily_constraints as dc
import daily_empirical as de
import test_event_recognition as f
from event_observation_read import _read,read_batch

class CalculationWorkTests(unittest.TestCase):
    def test_branch_queue_matches_full_rescan(self):
        rng=random.Random(650)
        for _ in range(200):
            domains=[[(D(k),D(k)+D('.2')) for k in sorted(rng.sample(range(25),8))] for _ in range(8)]
            edges=[(i,i+1,D(0),D(10)) for i in range(7)]+[(0,7,D(5),D(20))]
            links=[[] for _ in domains]
            for n,(i,j,_,_) in enumerate(edges):links[i].append(n);links[j].append(n)
            base=dc.propagate(domains,edges,links,dc.Budget())
            if base is None:continue
            for index in (0,3,7):
                for band in base[index]:
                    branch=list(base);branch[index]=[band]
                    self.assertEqual(dc.propagate(branch,edges,links,dc.Budget(),links[index]),dc.propagate(branch,edges,links,dc.Budget()))

    def test_linear_intersection_matches_cartesian(self):
        rng=random.Random(65)
        for _ in range(1500):
            def domain():
                return dc.merge([(D(a)/10,D(a+rng.randrange(8))/10) for a in rng.sample(range(100),rng.randrange(1,20))])
            a,b=domain(),domain();lo=D(rng.randrange(-20,20))/10;hi=lo+D(rng.randrange(20))/10
            expected=dc.merge([(max(x,u+lo),min(y,v+hi)) for x,y in a for u,v in b if max(x,u+lo)<=min(y,v+hi)])
            self.assertEqual(dc.supported(a,b,lo,hi),expected)

    def test_selected_endpoints_preserve_comparison_edges(self):
        import test_daily_constraints as fixture
        f=fixture.DailyConstraintsTests();rows=[f.row(i+1,i*6,[(100,101)]) for i in range(1500)]
        values=[D(i)/100 for i in range(len(rows))]
        expected=de.comparisons(rows,values,D(6),dc.Budget())
        needed={i for pair in de.comparison_pairs(rows,dc.Budget()) for i in pair}
        self.assertLess(len(needed),len(rows))
        self.assertEqual(de.comparisons(rows,{i:values[i] for i in needed},D(6),dc.Budget()),expected)

class SavedBatchTests(unittest.TestCase):
    def setUp(self):
        self.f=f.EventRecognitionTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        event,sha,result=self.f.complete(1000000)
        self.source=result['event_observation'];self.event=event;self.sha=sha
    def compare(self,db):
        source=self.source
        one=_read(db,self.event,self.sha,f.PIPELINE,source['context_id'],{})
        self.assertEqual(read_batch(db,[source],f.PIPELINE),[one])
    def test_identical_and_read_only(self):
        with self.f.store.connect() as db:
            before=list(db.iterdump());self.compare(db)
            self.assertEqual(list(db.iterdump()),before)
            db.execute('PRAGMA query_only=ON');self.compare(db)
    def test_wrong_identity_rejected(self):
        with self.f.store.connect() as db:
            for key,value in [('context_id','f'*64),('source_sha256','f'*64)]:
                source=dict(self.source,**{key:value})
                with self.assertRaises(ValueError):read_batch(db,[source],f.PIPELINE)
    def test_corrupt_request_binding_and_cache_rejected(self):
        changes=["UPDATE event_recognition_requests SET request='{}'",
                 "UPDATE event_recognition_bindings SET request_sha='bad'",
                 "UPDATE event_recognition_bindings SET mask_sha='bad'",
                 "UPDATE event_recognition_bindings SET source_sha='bad'",
                 "UPDATE event_recognition_cache SET result='{}'",
                 "UPDATE event_recognition_cache SET mask='[]'",
                 "UPDATE event_recognition_cache SET result_sha='bad'"]
        with self.f.store.connect() as db:
            for sql in changes:
                db.execute('SAVEPOINT tamper');db.execute(sql)
                try:
                    with self.assertRaises(ValueError):read_batch(db,[self.source],f.PIPELINE)
                finally:db.execute('ROLLBACK TO tamper');db.execute('RELEASE tamper')
    def test_missing_request_and_binding_same_pending(self):
        with self.f.store.connect() as db:
            for table in ('event_recognition_requests','event_recognition_bindings'):
                db.execute('SAVEPOINT missing');db.execute('DELETE FROM '+table)
                try:self.compare(db)
                finally:db.execute('ROLLBACK TO missing');db.execute('RELEASE missing')
    def test_batch_limit_and_duplicates(self):
        with self.f.store.connect() as db:
            for sources in ([],[self.source]*2,[self.source]*65):
                with self.assertRaises(ValueError):read_batch(db,sources,f.PIPELINE)

if __name__=='__main__':unittest.main()
