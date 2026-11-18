import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from daily_constraints import Budget
from resumed_evidence import REVIEW_FILE, gap_edges, reviewed_edges


class ResumedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'images').mkdir()
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.policy = {'pipeline_id':'p','format_id':'f','capacity_cfh':775,'slow_allowance_ft3':6}
        self.rows = []
        for event,tick in enumerate((0,6,100,106),1):
            body = bytes([event])
            digest = hashlib.sha256(body).hexdigest()
            src = dict(event_id=event,source_sha256=digest,clock_id='t',context_id='x',
                       captured_at=str(tick),monotonic_us=tick*1000000,camera='local',format_id='f')
            self.rows.append(dict(event_id=event,event_observation=src))
            (self.root/'images'/(digest+'.jpg')).write_bytes(body)
        self.sources = [r['event_observation'] for r in self.rows]
        self.review = {'version':1,'origin':1,'pipeline_id':'p','intervals':[
            dict(kind='pointer_photos',movement_ft3='0.4',allowance_ft3='4',endpoints=self.sources[1:3]),
            dict(kind='saved_slow_readings',movement_ft3='0.2',allowance_ft3='4',endpoints=self.sources[2:])]}
        self.write_review()
        def saved(db,first,last,segment):
            return (r for r in self.rows if first<=r['event_id']<=last)
        mocks = [patch('daily_records.daily_records',saved),
                 patch('resumed_evidence.evidence',return_value=[Decimal(0),Decimal('.2')])]
        for mock in mocks:
            mock.start()
            self.addCleanup(mock.stop)

    def write_review(self):
        (self.root/REVIEW_FILE).write_text(json.dumps(self.review))

    def reviewed(self,through=4):
        return reviewed_edges(self.db,self.root,self.policy,1,through,'seg',Budget())

    def test_matching_pair_bounds_and_identity(self):
        edges, digest, allowance = self.reviewed()
        self.assertEqual(edges,[(2,3,0,Decimal('4.4')),(3,4,0,Decimal('4.2'))])
        self.assertEqual(allowance,4)
        self.assertEqual(digest,hashlib.sha256((self.root/REVIEW_FILE).read_bytes()).hexdigest())

    def test_missing_or_corrupt_photo_after_success(self):
        self.reviewed()
        p=self.root/'images'/(self.sources[1]['source_sha256']+'.jpg')
        p.write_bytes(b'other')
        with self.assertRaises(ValueError): self.reviewed()
        p.unlink()
        with self.assertRaises(ValueError): self.reviewed()

    def test_no_future_endpoint(self):
        with self.assertRaises(ValueError): self.reviewed(3)

    def test_changed_source_or_movement(self):
        self.review['intervals'][0]['endpoints']=copy.deepcopy(self.sources[1:3])
        self.review['intervals'][0]['endpoints'][0]['context_id']='z'
        self.write_review()
        with self.assertRaises(ValueError): self.reviewed()
        self.review['intervals'][0]['endpoints']=self.sources[1:3]
        self.review['intervals'][1]['movement_ft3']='5.2'
        self.write_review()
        with self.assertRaises(ValueError): self.reviewed()

    def test_inconclusive_or_invalid_review(self):
        self.review['intervals'][0]['allowance_ft3']='nan'
        self.write_review()
        with self.assertRaises(ValueError): self.reviewed()
        (self.root/REVIEW_FILE).write_text('{}')
        with self.assertRaises((KeyError,ValueError)): self.reviewed()

    def test_candidate_positions_only_rank_source_verified_limits(self):
        self.db.execute('create table event_recognition_bindings(event_id,context,pipeline,source_sha,mask_sha)')
        self.db.execute('create table event_recognition_cache(source_sha,pipeline,mask_sha,result)')
        for i in range(4):
            self.db.execute('insert into event_recognition_bindings values(?,?,?,?,?)',(i+1,'x','p',str(i),'m'))
            self.db.execute('insert into event_recognition_cache values(?,?,?,?)',
                            (str(i),'p','m',json.dumps({'dial_positions':[{'position':i/100},{'position':0}]})))
        with patch('resumed_evidence.interval_edges',return_value=[]):
            edges=gap_edges(self.db,self.rows,self.policy,Budget())
        self.assertEqual(len(edges),1)
        self.assertEqual(edges[0][2:],(0,Decimal('6.2')))

    def test_context_boundary_has_no_extra_edge(self):
        for source in self.sources[2:]: source['context_id']='other'
        with patch('resumed_evidence.interval_edges',return_value=[]):
            from unittest.mock import Mock
            db=Mock()
            db.execute.return_value=[(s['event_id'],s['context_id'],3,4) for s in self.sources]
            self.assertEqual(gap_edges(db,self.rows,self.policy,Budget()),[])

    def test_normal_cadence_skips_lookup(self):
        with patch('resumed_evidence.interval_edges',return_value=[]):
            self.assertEqual(gap_edges(None,self.rows[:2],self.policy,Budget()),[])
