"""Capture events survive paging, database maintenance and duplicate images."""
import hashlib,json,sqlite3,tempfile,threading,unittest,urllib.request,urllib.error
from contextlib import closing
from pathlib import Path
from http.server import ThreadingHTTPServer
from capture import Store
from service import handler
from test_capture import JPEG,headers

class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.store=Store(self.root)
    def tearDown(self):self.temp.cleanup()
    def add(self,frame,blob=JPEG):return self.store.add('fixture',blob,headers(str(frame),blob))
    def test_paging_does_not_skip_when_a_new_capture_arrives(self):
        for i in range(125):self.add(i)
        first=self.store.history()
        self.assertEqual([r['event_id'] for r in first['items']],list(range(125,75,-1)))
        self.assertEqual(first['next_before'],76)
        self.add(125)
        second=self.store.history(first['next_before'])
        third=self.store.history(second['next_before'])
        ids=[r['event_id'] for page in (first,second,third) for r in page['items']]
        self.assertEqual(ids,list(range(125,0,-1)))
        self.assertIsNone(third['next_before'])
        self.assertEqual(self.store.history()['items'][0]['event_id'],126)
        self.assertEqual(len(list((self.root/'images').glob('*.jpg'))),1)
        self.assertTrue(first['items'][0]['duplicate_image'])
        self.assertFalse(third['items'][-1]['duplicate_image'])
        self.assertTrue(all(not r['training_allowed'] for r in first['items']))
    def test_repeated_frame_is_not_a_new_event_and_ids_survive_vacuum(self):
        self.add(1);self.add(2)
        self.assertFalse(self.add(2));prior=self.store.history()
        with closing(sqlite3.connect(self.root/'captures.sqlite3')) as db:db.execute('VACUUM')
        self.assertEqual(Store(self.root).history(),prior)
        self.add(3);self.assertEqual(self.store.history()['items'][0]['event_id'],3)
    def test_legacy_migration_keeps_timestamps_images_and_results(self):
        # Build the pre-event schema separately, with two captures of one image.
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'images').mkdir();digest=hashlib.sha256(JPEG).hexdigest()
            (root/'images'/(digest+'.jpg')).write_bytes(JPEG)
            with closing(sqlite3.connect(root/'captures.sqlite3')) as db:
                db.executescript('CREATE TABLE frames(camera TEXT,frame_id TEXT,captured_at TEXT,received_at TEXT,sha256 TEXT,bytes INTEGER,training_allowed INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(camera,frame_id));CREATE TABLE failures(received_at TEXT,error TEXT);CREATE TABLE inference(sha256 TEXT,pipeline TEXT,processed_at TEXT,result TEXT,PRIMARY KEY(sha256,pipeline));')
                rows=[('camera','a','2026-01-01T00:00:00+00:00','2026-01-01T00:00:02+00:00',digest,len(JPEG),0),('camera','b','2026-01-01T00:00:30+00:00','2026-01-01T00:00:32+00:00',digest,len(JPEG),0)]
                db.executemany('INSERT INTO frames VALUES(?,?,?,?,?,?,?)',rows)
                db.execute('INSERT INTO inference VALUES(?,?,?,?)',(digest,'fixture','time','{}'));db.commit()
            store=Store(root);events=store.history()['items']
            self.assertEqual([r['frame_id'] for r in events],['b','a'])
            self.assertEqual(events[-1]['captured_at'],rows[0][2])
            self.assertEqual(events[-1]['received_at'],rows[0][3])
            self.assertEqual(store.image(digest),JPEG)
            with store.connect() as db:
                self.assertEqual(db.execute('SELECT * FROM frames ORDER BY frame_id').fetchall(),rows)
                self.assertEqual(db.execute('SELECT result FROM inference').fetchone(),('{}',))
            self.assertEqual(Store(root).history(),store.history())
    def test_invalid_cursors_are_rejected(self):
        for before,limit in [(0,50),(-1,50),(True,50),(2**63,50),(None,0),(None,101),(None,True)]:
            with self.subTest(before=before,limit=limit),self.assertRaises(ValueError):self.store.history(before,limit)
    def test_http_history_is_bounded_and_validates_query(self):
        for i in range(3):self.add(i)
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.store,False,None))
        thread=threading.Thread(target=server.serve_forever);thread.start();origin=f'http://127.0.0.1:{server.server_port}'
        try:
            with urllib.request.urlopen(origin+'/api/capture-history?limit=2') as response:page=json.load(response)
            self.assertEqual(len(page['items']),2);self.assertEqual(page['next_before'],2)
            with urllib.request.urlopen(origin+'/api/capture-history?before=2&limit=2') as response:page=json.load(response)
            self.assertEqual(len(page['items']),1);self.assertIsNone(page['next_before'])
            for query in ('limit=101','before=0','before=x','before=1&before=2','extra=x','limit=2&before=1&extra=x'):
                with self.subTest(query=query),self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(origin+'/api/capture-history?'+query)
                raised.exception.close();self.assertEqual(raised.exception.code,400)
        finally:server.shutdown();thread.join();server.server_close()

if __name__=='__main__':unittest.main()
