import json
from pathlib import Path
import tempfile
import unittest
from collect_cycle_trial import collect, endpoint, MAX_BODY
from test_cycle_trial_analysis import initial,cycle

class Clock:
    def __init__(self):self.now=0
    def read(self):return self.now
    def sleep(self,n):self.now+=n

class CollectorTests(unittest.TestCase):
    def run_trial(self, replies, cost=.2):
        clock=Clock();calls=[]
        def fetch(url,timeout,auth):
            calls.append((url,timeout,auth));clock.now+=cost
            result=replies[len(calls)-1]
            if isinstance(result,Exception):raise result
            return result
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        output=Path(folder.name)/'trial'
        result=collect('http://127.0.0.1:12345',output,len(replies),10,3,
                       fetch=fetch,monotonic=clock.read,sleep=clock.sleep,authorization='secret')
        return result,output,calls,clock
    def body(self,n,boot='a'):
        snapshot=initial() if n==0 else cycle(n)
        snapshot['boot_id']=boot*32
        return 200,json.dumps(snapshot).encode()
    def test_restart_separation_and_raw_preservation(self):
        replies=[self.body(0),self.body(1),self.body(0,'b'),self.body(1,'b')]
        result,out,calls,clock=self.run_trial(replies)
        self.assertEqual(len(result['boots']),2)
        self.assertEqual(result['successful_responses'],4)
        self.assertEqual((out/'0001.response').read_bytes(),replies[1][1])
        self.assertNotIn('secret',(out/'summary.json').read_text()+(out/'requests.jsonl').read_text())
        self.assertEqual({c[0] for c in calls},{'http://127.0.0.1:12345/cycle_timing'})
    def test_failures_stop_and_are_not_success_samples(self):
        result,out,calls,_=self.run_trial([(503,b'busy'),TimeoutError(),(200,b'not json'),self.body(1)])
        self.assertTrue(result['consecutive_failure_stop'])
        self.assertEqual(len(calls),3)
        self.assertEqual(result['failures'],3)
        self.assertEqual(result['boots'],{})
    def test_no_burst_catchup(self):
        result,_,calls,clock=self.run_trial([self.body(1),self.body(2)],cost=23)
        self.assertEqual(result['skipped_collector_poll_slots'],4)
        self.assertEqual(clock.now,53)
    def test_size_limit_and_missing_identity(self):
        result,_,_,_=self.run_trial([(200,b'x'*(MAX_BODY+1)),(200,json.dumps(initial()).encode())])
        self.assertEqual(result['failures'],2)
    def test_aggregate_counter_regression_is_visible(self):
        result,_,_,_=self.run_trial([self.body(2),self.body(1)])
        self.assertTrue(result['boots']['a'*32]['invalid'])
    def test_unsafe_origins_and_overwrite_rejected(self):
        for url in ('file:///tmp/a','http://user:pass@host','http://host/stream','http://host?x=y','http://host/#x'):
            with self.subTest(url=url),self.assertRaises(ValueError):endpoint(url)
        with tempfile.TemporaryDirectory() as folder,self.assertRaises(FileExistsError):
            collect('http://localhost',folder,1,fetch=lambda *a:self.fail('must not fetch'))

if __name__=='__main__':unittest.main()
