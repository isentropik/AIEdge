import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from capture import Store
from setup_store import Setup
from saved_file import SavedFile
from durable_file import sync_directory
from test_capture import JPEG,headers

class DurabilityTests(unittest.TestCase):
    def test_posix_directory_descriptor_is_flushed_and_closed(self):
        with patch('durable_file.DIRECTORY_FSYNC',True),patch('durable_file.os.open',return_value=42) as opened,patch('durable_file.os.fsync') as flush,patch('durable_file.os.close') as close:
            self.assertTrue(sync_directory('directory'))
            self.assertEqual(opened.call_args.args[0],'directory');flush.assert_called_once_with(42);close.assert_called_once_with(42)
    def test_flush_failure_propagates_and_closes_descriptor(self):
        with patch('durable_file.DIRECTORY_FSYNC',True),patch('durable_file.os.open',return_value=42),patch('durable_file.os.fsync',side_effect=OSError('flush failed')),patch('durable_file.os.close') as close:
            with self.assertRaises(OSError):sync_directory('directory')
            close.assert_called_once_with(42)
    def test_unsupported_platform_does_not_claim_directory_flush(self):
        with patch('durable_file.DIRECTORY_FSYNC',False),patch('durable_file.os.open') as opened:
            self.assertFalse(sync_directory('directory'));opened.assert_not_called()
    def test_image_directory_failure_does_not_commit_a_ledger_row(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory)
            with patch('capture.sync_directory',side_effect=OSError('directory flush failed')):
                with self.assertRaises(OSError):store.add('fixture',JPEG,headers())
            self.assertEqual(store.status()['captures'],0)
            files=list((Path(directory)/'images').glob('*.jpg'))
            self.assertEqual(len(files),1);self.assertEqual(files[0].read_bytes(),JPEG)
            # A retry verifies the retained file and repeats the directory flush.
            with patch('capture.sync_directory') as flush:self.assertTrue(store.add('fixture',JPEG,headers()))
            flush.assert_called_once_with(Path(directory)/'images')
            self.assertEqual(store.status()['captures'],1)
    def test_configuration_flush_failure_requires_readback_before_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json';path.write_bytes(b'old');saved=SavedFile(path);saved.read()
            with patch('setup_store.sync_directory',side_effect=OSError('flush failed')):
                with self.assertRaises(OSError):saved.replace(b'new',Setup._atomic,'changed')
            # Rename happened, durability did not complete. Do not claim rollback.
            self.assertEqual(path.read_bytes(),b'new')
            with self.assertRaisesRegex(ValueError,'changed'):saved.replace(b'another',Setup._atomic,'changed')
            self.assertEqual(path.read_bytes(),b'new')
    def test_recovery_directory_flush_failure_keeps_original_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'config.json';path.write_bytes(b'broken');saved=SavedFile(path);saved.read();saved.failed('invalid')
            with patch('saved_file.sync_directory',side_effect=OSError('flush failed')):
                with self.assertRaises(OSError):saved.replace(b'{}',Setup._atomic,'changed')
            self.assertEqual(path.read_bytes(),b'broken');self.assertEqual(saved.error,'invalid')

if __name__=='__main__':unittest.main()
