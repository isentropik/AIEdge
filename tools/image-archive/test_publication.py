import os,tempfile,unittest
from pathlib import Path
from image_archive_store import publish_no_replace

class PublicationTests(unittest.TestCase):
 def test_existing_destination_never_changes(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);source=root/'source';target=root/'target'
   source.write_bytes(b'new');target.write_bytes(b'original')
   with self.assertRaises(OSError):publish_no_replace(source,target)
   self.assertEqual(target.read_bytes(),b'original')
   self.assertEqual(source.read_bytes(),b'new')
 def test_new_destination_exact_bytes(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);source=root/'source';target=root/'target'
   source.write_bytes(b'complete');publish_no_replace(source,target)
   self.assertEqual(target.read_bytes(),b'complete')
   self.assertEqual(source.exists(),os.name!='nt')
if __name__=='__main__':unittest.main()
