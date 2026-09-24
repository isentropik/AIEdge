import errno,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from probe_archive_storage import probe

class ProbeTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.existing=self.root/'existing.txt';self.existing.write_bytes(b'keep')
 def test_success_is_separate_and_existing_files_unchanged(self):
  one=probe(self.root);two=probe(self.root)
  self.assertTrue(one['passed']);self.assertTrue(two['passed']);self.assertNotEqual(one['probe_folder'],two['probe_folder'])
  self.assertEqual(len(one['checks']),4);self.assertFalse(one['power_loss_durability_verified'])
  self.assertEqual(self.existing.read_bytes(),b'keep')
  self.assertEqual(json.loads((Path(one['probe_folder'])/'result.json').read_text()),one)
 def test_unsupported_link_is_reported_and_never_success(self):
  with patch('image_archive_store.publish_no_replace',side_effect=OSError(errno.EPERM,'unsupported')):r=probe(self.root)
  self.assertFalse(r['passed']);self.assertEqual(r['failure']['errno'],errno.EPERM)
  self.assertEqual(r['failure']['stage'],'create_flush_publish_readback')
  self.assertFalse(list(Path(r['probe_folder']).rglob('test.bin')))
  self.assertEqual(self.existing.read_bytes(),b'keep')
 def test_disk_full_is_failure(self):
  with patch('image_archive_store.publish_no_replace',side_effect=OSError(errno.ENOSPC,'full')):r=probe(self.root)
  self.assertFalse(r['passed']);self.assertEqual(r['failure']['errno'],errno.ENOSPC)
 def test_competing_failure_is_not_reported_as_success(self):
  with patch('probe_archive_storage.competing_writes',side_effect=ValueError('wrong winner')):r=probe(self.root)
  self.assertFalse(r['passed']);self.assertEqual(r['failure']['stage'],'competing_writes_and_retry')
  self.assertEqual(self.existing.read_bytes(),b'keep')
 def test_missing_or_file_destination_is_rejected(self):
  for path in [self.root/'missing',self.existing]:
   with self.assertRaises(ValueError):probe(path)
  self.assertEqual(sorted(p.name for p in self.root.iterdir()),['existing.txt'])
if __name__=='__main__':unittest.main()
