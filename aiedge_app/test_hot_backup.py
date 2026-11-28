import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest

import hot_backup as hot
from capture import Store, now
from hashlib import sha256


class HotBackupTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)/'source'
        self.root.mkdir()
        self.options = b'{"capture_enabled":true}'
        (self.root/'options.json').write_bytes(self.options)
        self.store = Store(self.root)
        self.photo(1)
        self.store.fail('camera_timeout')
        state = hot.startup(self.root)
        self.store = Store(state)

    def photo(self, n):
        blob=b'\xff\xd8'+bytes([n])+b'\xff\xd9'
        self.assertTrue(self.store.add('test',blob,{'X-AIEdge-Frame-Id':str(n),'X-AIEdge-Captured-At':now(),
                                                  'X-AIEdge-SHA256':sha256(blob).hexdigest()}))

    def extracted(self):
        dest=self.root.parent/'restore'
        shutil.copytree(self.root,dest,ignore=shutil.ignore_patterns(hot.WORK))
        return dest

    def test_live_writes_and_isolated_restore(self):
        hot.prepare(self.root, lambda:self.photo(2))
        self.assertEqual(self.store.publication_frame()[0],2)
        restore=self.extracted()
        restored=Store(hot.startup(restore))
        self.assertEqual(restored.publication_frame()[0],1)
        with restored.connect() as db:
            self.assertEqual(db.execute('SELECT after_event_id,error,outcome FROM capture_failure_boundaries').fetchall(),
                             [(1,'camera_timeout','unknown')])
        self.assertEqual((restore/'options.json').read_bytes(),self.options)
        self.assertEqual(Store(hot.startup(self.root)).publication_frame()[0],2)
        self.store=restored
        self.photo(3)
        self.assertEqual(Store(hot.startup(restore)).publication_frame()[0],2)

    def test_corruption_refuses_to_start_and_preserves_raw_fallback(self):
        hot.prepare(self.root)
        restore=self.extracted()
        photo,=(restore/hot.SEALED/'state/images').glob('*.jpg'); photo.unlink()
        with self.assertRaisesRegex(ValueError,'file list'):
            hot.startup(restore)
        self.assertTrue((restore/hot.STATE/'captures.sqlite3').is_file())
        self.assertTrue((restore/hot.SEALED/'manifest.json').is_file())

    def test_supervisor_tar_contains_independent_photo_members(self):
        hot.prepare(self.root)
        live, = (self.root/hot.STATE/'images').glob('*.jpg')
        sealed = self.root/hot.SEALED/'state/images'/live.name
        self.assertFalse(live.samefile(sealed))
        archive = self.root.parent/'backup.tar'
        with tarfile.open(archive, 'w|') as writer:
            writer.add(sealed, 'sealed.jpg')
            writer.add(live, 'live.jpg')
        with tarfile.open(archive, 'r|') as reader:
            photos = []
            for member in reader:
                self.assertTrue(member.isfile())
                photos.append(reader.extractfile(member).read())
            self.assertEqual(photos, [live.read_bytes(), live.read_bytes()])

    def test_raw_stopped_backup_and_partial_migration(self):
        (self.root/'extra-setting.json').write_text('{}')
        hot.startup(self.root)
        self.assertEqual((self.root/hot.STATE/'extra-setting.json').read_text(),'{}')
        self.assertEqual(Store(hot.startup(self.extracted())).publication_frame()[0],1)

    def test_retry_after_rename_before_restored_state_installed(self):
        gen=hot.prepare(self.root)
        restore=self.extracted()
        work=restore/hot.WORK; work.mkdir()
        (restore/hot.STATE).rename(work/('before-'+gen))
        self.assertEqual(Store(hot.startup(restore)).publication_frame()[0],1)
        self.assertFalse((work/('before-'+gen)).exists())

    def test_one_shot_restore_after_install_before_cleanup(self):
        gen=hot.prepare(self.root)
        restore=self.extracted()
        manifest=json.loads((restore/hot.SEALED/'manifest.json').read_text())
        self.assertEqual(manifest['generation'],gen)
        old=restore/hot.WORK/('before-'+gen); old.parent.mkdir()
        (restore/hot.STATE).rename(old)
        (restore/hot.SEALED/'state').rename(restore/hot.STATE)
        (restore/hot.STATE/hot.GEN).write_text(gen)
        self.assertEqual(Store(hot.startup(restore)).publication_frame()[0],1)

    def test_short_disk_fails_hook_and_capture_can_continue(self):
        from unittest.mock import patch
        hot.prepare(self.root)
        with patch('hot_backup.free_for',side_effect=OSError('insufficient space')):
            with self.assertRaisesRegex(OSError,'insufficient'):
                hot.prepare(self.root)
        self.assertFalse((self.root/hot.SEALED).exists())
        self.photo(2)

    def test_backup_waits_for_photo_outcome_without_making_a_gap(self):
        attempt = 'f'*32
        with self.store.connect() as db:
            db.execute('INSERT INTO continuous_capture_attempts VALUES(?,?,?,?)',(attempt,1,1,now()))
        def finish():
            self.photo(2)
            with self.store.connect() as db:
                db.execute('INSERT INTO continuous_capture_outcomes VALUES(?,?,?,?,?)',(attempt,'committed',2,None,now()))
        from unittest.mock import patch
        with patch('hot_backup.time.sleep', side_effect=lambda _:finish()) as delay:
            hot.prepare(self.root)
        delay.assert_called_once()
        restored = Store(hot.startup(self.extracted()))
        self.assertEqual(restored.publication_frame()[0],2)
