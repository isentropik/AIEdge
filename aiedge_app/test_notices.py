import json,shutil,tempfile,unittest
from pathlib import Path
from verify_notices import verify

class NoticeTests(unittest.TestCase):
    def test_packaged_notices_match_lock(self):
        result=verify();self.assertEqual(result['packages'],11);self.assertGreater(result['notice_texts'],11)
        self.assertFalse(result['complete_distribution_review'])
    def test_changed_dependency_or_notice_fails(self):
        source=Path(__file__).parent
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);shutil.copytree(source/'third-party',root/'third-party')
            shutil.copyfile(source/'requirements-linux-amd64.lock',root/'requirements-linux-amd64.lock')
            lock=root/'requirements-linux-amd64.lock';original=lock.read_text(encoding='utf-8')
            lock.write_text(original.replace('paho-mqtt==2.1.0','paho-mqtt==2.2.0'),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'dependency_lock'):verify(root)
            lock.write_text(original,encoding='utf-8')
            notice=next((root/'third-party').glob('*.txt'));notice.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'hash_mismatch'):verify(root)

if __name__=='__main__':unittest.main()
