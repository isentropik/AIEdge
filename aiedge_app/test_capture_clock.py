"""Clock discontinuities must never turn into fabricated elapsed time."""
import json,sqlite3,tempfile,unittest
from pathlib import Path
from capture import Store
from capture_clock import parse,interval,CLOCK_HEADER,TICK_HEADER,MAX_TICK
from diagnostics import build
from test_capture import JPEG,headers

def timed(frame='a',tick=1000000,clock='boot-a',stamp='2026-01-01T00:00:00Z'):
    h=headers(frame);h.replace_header('X-AIEdge-Captured-At',stamp)
    h[CLOCK_HEADER]=clock;h[TICK_HEADER]=str(tick)
    return h

def row(tick=1000000,clock='boot-a',stamp='2026-01-01T00:00:00Z',camera='camera'):
    return {'camera':camera,'clock_id':clock,'monotonic_us':tick,'captured_at':stamp}

class ClockTests(unittest.TestCase):
    def test_optional_pair_is_strict_and_bounded(self):
        self.assertIsNone(parse(headers()))
        self.assertEqual(parse(timed()),('boot-a',1000000))
        for tick in (0,MAX_TICK):self.assertEqual(parse(timed(tick=tick))[1],tick)
        for name,value in ((TICK_HEADER,'-1'),(TICK_HEADER,'01'),(TICK_HEADER,'1.0'),
                           (TICK_HEADER,'1e6'),(TICK_HEADER,str(MAX_TICK+1)),(TICK_HEADER,'9'*1000),
                           (CLOCK_HEADER,''),(CLOCK_HEADER,'../boot'),(CLOCK_HEADER,'x'*129)):
            h=timed();h.replace_header(name,value)
            with self.subTest(name=name,value=value[:20]),self.assertRaises(ValueError):parse(h)
        for name in (CLOCK_HEADER,TICK_HEADER):
            h=timed();del h[name]
            with self.assertRaisesRegex(ValueError,'incomplete'):parse(h)
            h=timed();h[name]=h[name]
            with self.assertRaisesRegex(ValueError,'duplicate'):parse(h)
    def test_elapsed_uses_monotonic_clock_not_arrival_or_frame_id(self):
        a=row();b=row(31000000,stamp='2026-01-01T00:00:30.100000Z')
        a.update(received_at='2026-01-01T00:10:00Z',frame_id='unexpected-old-id')
        b.update(received_at='2026-01-01T00:20:00Z',frame_id='different-new-id')
        self.assertEqual(interval(a,b),{'state':'continuous','reason':None,'elapsed_seconds':30.0})
    def test_boot_reset_and_nonincreasing_time_need_new_anchor(self):
        for b,reason in ((row(31000000,clock='boot-b',stamp='2026-01-01T00:00:30Z'),'capture_clock_changed'),
                         (row(),'capture_clock_not_increasing'),(row(0),'capture_clock_not_increasing'),
                         (row(camera='another'),'capture_camera_changed')):
            with self.subTest(reason=reason):
                result=interval(row(),b);self.assertEqual(result['reason'],reason);self.assertIsNone(result['elapsed_seconds'])
    def test_wall_clock_jump_or_reversal_is_not_elapsed_time(self):
        for stamp in ('2026-01-01T00:00:31Z','2025-12-31T23:59:59Z','2026-01-01T00:00:00Z'):
            self.assertEqual(interval(row(),row(31000000,stamp=stamp))['reason'],'capture_clock_utc_discontinuity')
    def test_missing_malformed_or_timezone_free_clock_stays_unavailable(self):
        self.assertEqual(interval(None,row())['reason'],'capture_clock_anchor_missing')
        self.assertEqual(interval(row(clock=None),row())['reason'],'capture_clock_missing')
        for b in (row(True),row(MAX_TICK+1),row(31000000,stamp='broken'),row(31000000,stamp='2026-01-01T00:00:30')):
            self.assertEqual(interval(row(),b)['reason'],'capture_clock_invalid')
    def test_integer_precision_and_slew_boundary(self):
        base=MAX_TICK-60000000
        self.assertEqual(interval(row(base),row(base+30000000,stamp='2026-01-01T00:00:30.256000Z'))['elapsed_seconds'],30)
        self.assertEqual(interval(row(base),row(base+30000000,stamp='2026-01-01T00:00:30.256001Z'))['reason'],'capture_clock_utc_discontinuity')
    def test_metadata_persists_and_conflicts_do_not_rewrite_it(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);self.assertTrue(store.add('camera',JPEG,timed()))
            self.assertFalse(Store(directory).add('camera',JPEG,timed()))
            for h in (timed(tick=1000001),timed(clock='changed'),headers('a')):
                with self.assertRaisesRegex(ValueError,'frame_identity_conflict'):store.add('camera',JPEG,h)
            with store.connect() as db:self.assertEqual(db.execute('SELECT clock_id,monotonic_us FROM capture_clocks').fetchall(),[('boot-a',1000000)])
            self.assertEqual(store.status()['captures'],1)
            self.assertEqual(store.image(headers()['X-AIEdge-SHA256']),JPEG)
    def test_missing_clock_is_not_retroactively_invented(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);store.add('camera',JPEG,headers('a'))
            with self.assertRaisesRegex(ValueError,'frame_identity_conflict'):store.add('camera',JPEG,timed())
            with store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM capture_clocks').fetchone()[0],0)
    def test_legacy_frames_survive_migration_without_clock_backfill(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);store.add('camera',JPEG,headers('a'))
            with store.connect() as db:
                frames=db.execute('SELECT * FROM frames').fetchall();events=db.execute('SELECT * FROM capture_events').fetchall()
                db.execute('DROP TABLE capture_clocks')
            store=Store(directory)
            with store.connect() as db:
                self.assertEqual(db.execute('SELECT * FROM frames').fetchall(),frames)
                self.assertEqual(db.execute('SELECT * FROM capture_events').fetchall(),events)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM capture_clocks').fetchone()[0],0)
            self.assertEqual(store.status()['captures'],1)
    def test_latest_timing_survives_restart_and_does_not_skip_missing_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);store.add('camera',JPEG,timed())
            store.add('camera',JPEG,timed('b',31000000,stamp='2026-01-01T00:00:30Z'))
            self.assertEqual(Store(directory).capture_timing()['elapsed_seconds'],30)
            # A different camera cannot supply the previous capture for this one.
            store.add('other-camera',JPEG,timed('x',1000000))
            self.assertEqual(store.capture_timing()['reason'],'capture_clock_anchor_missing')
            store.add('camera',JPEG,headers('c'))
            store.add('camera',JPEG,timed('d',91000000,stamp='2026-01-01T00:01:30Z'))
            self.assertEqual(store.capture_timing()['reason'],'capture_clock_missing')
            self.assertEqual(store.status()['unique_images'],1)
            self.assertEqual(store.status()['captures'],5)
    def test_invalid_clock_headers_leave_no_file_or_database_record(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);h=timed();del h[CLOCK_HEADER]
            with self.assertRaises(ValueError):store.add('camera',JPEG,h)
            self.assertEqual(store.status()['captures'],0)
            self.assertEqual(list((Path(directory)/'images').iterdir()),[])
    def test_orphan_clock_record_blocks_startup_without_rewriting_database(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            with store.connect() as db:db.execute('INSERT INTO capture_clocks VALUES(?,?,?,?)',('camera','missing','boot',1))
            path=Path(directory)/'captures.sqlite3';original=path.read_bytes()
            with self.assertRaisesRegex(sqlite3.DatabaseError,'capture_clock_without_frame'):Store(directory)
            self.assertEqual(path.read_bytes(),original)
    def test_diagnostics_reports_timing_without_clock_identifiers(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            store.add('PRIVATE-CAMERA',JPEG,timed(clock='PRIVATE-BOOT'))
            store.add('PRIVATE-CAMERA',JPEG,timed('b',31000000,clock='PRIVATE-BOOT',stamp='2026-01-01T00:00:30Z'))
            report=build(store);self.assertEqual(report['capture']['timing']['elapsed_seconds'],30)
            self.assertNotIn('PRIVATE-',json.dumps(report))

if __name__=='__main__':unittest.main()
