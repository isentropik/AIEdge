"""Real HTTPS receiver test on loopback with disposable certificates/storage."""
import base64
from datetime import datetime, timedelta, timezone
import http.client
import ipaddress
import json
from pathlib import Path
import socket
import ssl
import tempfile
import threading
import unittest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from image_archive_receiver import ArchiveServer
from image_archive_store import canonical, digest

class TLSTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
  name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'archive-test')])
  now=datetime.now(timezone.utc)
  cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
   .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
   .not_valid_after(now+timedelta(hours=1)).add_extension(x509.SubjectAlternativeName([
    x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).sign(key,hashes.SHA256()))
  certfile=self.root/'test.pem';keyfile=self.root/'test-key.pem'
  certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
  keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
  context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
  context.load_cert_chain(certfile,keyfile)
  self.client=ssl.create_default_context(cafile=str(certfile))
  self.token='a'*40;self.archive=self.root/'archive'
  self.server=ArchiveServer(('127.0.0.1',0),self.archive,self.token,timeout=1)
  self.server.tls_context=context
  self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01});self.thread.start()
  self.addCleanup(self.stop)
  self.settings=b'capture-settings-v1\nsource=tls-test\n';self.image=b'original image bytes'
  self.metadata=dict(version=1,device_id='meter',boot_id='boot',capture_us=123,capture_utc=None,
   image_sha256=digest(self.image),image_bytes=len(self.image),firmware_sha256='1'*64,
   model_sha256='2'*64,calibration_sha256='3'*64,settings_sha256=digest(self.settings))
 def stop(self):
  self.server.shutdown();self.server.server_close();self.thread.join(3)
  self.assertFalse(self.thread.is_alive())
 def post(self,path,body,headers,context=None):
  connection=http.client.HTTPSConnection(*self.server.server_address,timeout=3,context=context or self.client)
  try:
   connection.request('POST',path,body,dict({'Authorization':'Bearer '+self.token,'Content-Type':'application/octet-stream'},**headers))
   response=connection.getresponse();return response.status,json.loads(response.read())
  finally:connection.close()
 def settings_post(self):return self.post('/v1/settings',self.settings,{'X-Settings-SHA256':digest(self.settings)})
 def capture_post(self):return self.post('/v1/captures',self.image,{'X-Meter-Metadata':base64.b64encode(canonical(self.metadata)).decode()})
 def test_verified_settings_capture_retry_and_readback(self):
  self.assertEqual(self.capture_post()[0],409)
  status,receipt=self.settings_post();self.assertEqual(status,201);self.assertTrue(receipt['verified_readback'])
  status,receipt=self.capture_post();self.assertEqual(status,201)
  self.assertFalse(receipt['training_eligible']);self.assertEqual(receipt['review_status'],'unreviewed')
  self.assertEqual((self.archive/'blobs'/f'{digest(self.image)}.image').read_bytes(),self.image)
  record=(self.archive/'captures'/f'{receipt["capture_id"]}.json').read_bytes()
  self.assertEqual(digest(record),receipt['record_sha256'])
  self.assertEqual(self.capture_post()[0],200)
 def test_untrusted_certificate_writes_nothing(self):
  with self.assertRaises(ssl.SSLCertVerificationError):
   self.post('/v1/settings',self.settings,{},ssl.create_default_context())
  self.assertFalse(self.archive.exists())
  self.assertEqual(self.settings_post()[0],201)
 def test_wrong_hostname_rejected(self):
  raw=socket.create_connection(self.server.server_address,timeout=3)
  try:
   with self.assertRaises(ssl.SSLCertVerificationError):self.client.wrap_socket(raw,server_hostname='wrong-host')
  finally:raw.close()
  self.assertFalse(self.archive.exists());self.assertEqual(self.settings_post()[0],201)
 def test_stalled_handshake_does_not_block_upload(self):
  with socket.create_connection(self.server.server_address,timeout=3) as stalled:
   self.assertEqual(self.settings_post()[0],201)
   self.assertEqual(stalled.recv(1),b'')
  self.assertEqual(self.capture_post()[0],201)
 def test_bad_token_writes_nothing(self):
  status,_=self.post('/v1/settings',self.settings,{'Authorization':'Bearer invalid','X-Settings-SHA256':digest(self.settings)})
  self.assertEqual(status,401);self.assertFalse(self.archive.exists())

if __name__=='__main__':unittest.main()
