"""Build identity must track source changes and stay honest for source archives."""
import importlib.util,json,subprocess,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('metadata',Path(__file__).resolve().parents[2]/'code/tools/build_metadata.py')
metadata=importlib.util.module_from_spec(spec);spec.loader.exec_module(metadata)
class IdentityTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name);self.repo=self.base/'repo';(self.repo/'code').mkdir(parents=True);(self.repo/'code/APP_VERSION').write_text('0.1.11-dev\n');self.out=self.base/'out'
 def git(self,*args):
  return subprocess.check_output(['git','-C',str(self.repo),*args],stderr=subprocess.STDOUT,text=True).strip()
 def init(self):
  self.git('init');self.git('config','user.name','Build test');self.git('config','user.email','test@example.invalid');self.git('add','.');self.git('commit','-m','Fixture')
 def test_source_archive(self):
  got=metadata.generate(self.repo,self.out,0);self.assertEqual(got['revision'],'source-archive');self.assertEqual(got['version'],'AIEdge 0.1.11-dev');self.assertEqual(got['built_at'],'1970-01-01 00:00:00 UTC')
 def test_clean_dirty_and_new_commit(self):
  self.init();first=metadata.generate(self.repo,self.out,1);self.assertEqual(first['revision'],self.git('rev-parse','--short=12','HEAD'))
  (self.repo/'code/new.cpp').write_text('changed');dirty=metadata.generate(self.repo,self.out,2);self.assertTrue(dirty['revision'].endswith('-dirty'))
  self.git('add','.');self.git('commit','-m','Changed');next=metadata.generate(self.repo,self.out,3);self.assertNotEqual(next['revision'],first['revision']);self.assertFalse(next['revision'].endswith('-dirty'))
  self.assertIn(next['revision'],(self.out/'version.cpp').read_text());self.assertEqual((self.out/'version.txt').read_text().splitlines()[1],next['revision'])
 def test_parent_checkout_not_used(self):
  self.init();nested=self.repo/'nested';(nested/'code').mkdir(parents=True);(nested/'code/APP_VERSION').write_text('0.2-dev');got=metadata.generate(nested,self.out,0);self.assertEqual(got['revision'],'source-archive')
 def test_repeat_is_reproducible(self):
  metadata.generate(self.repo,self.out,5);before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.out.iterdir()};metadata.generate(self.repo,self.out,5);self.assertEqual(before,{p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.out.iterdir()})
 def test_invalid_version(self):
  (self.repo/'code/APP_VERSION').write_text('bad"version');self.assertRaises(ValueError,metadata.generate,self.repo,self.out,0)
if __name__=='__main__':unittest.main()
