import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from prepare_archive_setup import prepare

class SetupTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
  name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'test-only')]);now=datetime.now(timezone.utc)
  cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1)).sign(key,hashes.SHA256())
  self.ca=self.root/'ca.pem';self.ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
 def make(self,**changes):
  args=dict(output=self.root/'setup',host='nas.local',folder='/srv/meter images',ca_file=self.ca,certificate='/etc/tls/server.pem',private_key='/etc/tls/key.pem')
  args.update(changes);return prepare(**args)
 def test_matching_pair(self):
  out=self.make();meter=out/'meter-config';server=out/'server'
  a=(meter/'image-archive-token.txt').read_text();self.assertEqual(a,(server/'archive-token.txt').read_text());self.assertRegex(a.strip(),r'^[A-Za-z0-9_-]{43}$')
  self.assertEqual(json.loads((meter/'image-archive.json').read_text())['host'],'nas.local')
  self.assertEqual((meter/'image-archive-ca.pem').read_bytes(),self.ca.read_bytes())
  args=json.loads((server/'receiver-arguments.json').read_text());self.assertEqual(args[args.index('--folder')+1],'/srv/meter images')
  self.assertEqual({p.name for p in meter.iterdir()},{'image-archive.json','image-archive-ca.pem','image-archive-token.txt','image-archive-settings.json'})
  unified=json.loads((meter/'image-archive-settings.json').read_text())
  self.assertEqual(unified,{'version':1,'config':json.loads((meter/'image-archive.json').read_text()),'token':a.strip(),'ca_pem':self.ca.read_text()})
  self.assertNotIn(a.strip(),(out/'README.md').read_text())
  with self.assertRaises(FileExistsError):self.make()
  self.assertEqual(a,(meter/'image-archive-token.txt').read_text())
 def test_ipv4_windows_paths(self):
  out=self.make(host='10.1.0.99',folder=r'D:\Meter Images',certificate=r'D:\TLS\cert.pem',private_key=r'D:\TLS\key.pem')
  self.assertEqual(json.loads((out/'meter-config/image-archive.json').read_text())['host'],'10.1.0.99')
 def test_invalid_inputs_no_output(self):
  for field,value in [('host','https://nas'),('host','nas:8766'),('host','x/y'),('device','../x'),('folder','relative'),('folder','/bad\npath'),('certificate','cert.pem'),('private_key','key.pem'),('port',0),('port',65536),('port',True)]:
   with self.subTest(field=field,value=value):
    with self.assertRaises(ValueError):self.make(**{field:value})
    self.assertFalse((self.root/'setup').exists())
 def test_invalid_ca_no_output(self):
  self.ca.write_text('not a certificate')
  with self.assertRaises((ValueError,OSError)):self.make()
  self.assertFalse((self.root/'setup').exists())
 def test_no_shell_interpretation(self):
  folder='/srv/images with spaces; $(not-a-command)'
  out=self.make(folder=folder)
  args=json.loads((out/'server/receiver-arguments.json').read_text())
  self.assertEqual(args[args.index('--folder')+1],folder)
  launcher=(out/'server/start_receiver.py').read_text();self.assertNotIn('shell=True',launcher)
  compile(launcher,'start_receiver.py','exec')
if __name__=='__main__':unittest.main()
