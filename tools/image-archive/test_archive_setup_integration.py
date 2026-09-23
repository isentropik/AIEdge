"""Launch the exact generated receiver with disposable TLS and local storage."""
import base64,json,http.client,ipaddress,os,socket,ssl,subprocess,sys,tempfile,time,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from prepare_archive_setup import prepare
from image_archive_store import canonical,digest

class GeneratedReceiverTest(unittest.TestCase):
 def test_generated_launcher_tls_upload(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);certfile=root/'server.pem';keyfile=root/'key.pem';archive=root/'image archive'
   key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
   name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'loopback-test')]);now=datetime.now(timezone.utc)
   cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(hours=1)).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).sign(key,hashes.SHA256())
   certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
   keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
   with socket.socket() as reserve:reserve.bind(('127.0.0.1',0));port=reserve.getsockname()[1]
   setup=prepare(root/'setup','127.0.0.1',str(archive),certfile,str(certfile),str(keyfile),port=port,bind='127.0.0.1')
   unified=json.loads((setup/'meter-config/image-archive-settings.json').read_text());config=unified['config'];token=unified['token']
   self.assertEqual(token,(setup/'server/archive-token.txt').read_text().strip())
   trust=ssl.create_default_context(cafile=str(setup/'meter-config/image-archive-ca.pem'))
   with open(os.devnull,'w+b') as log:
    process=subprocess.Popen([getattr(sys,'_base_executable',sys.executable),str(setup/'server/start_receiver.py')],cwd=root,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
     deadline=time.monotonic()+10
     while True:
      if process.poll() is not None:
       self.fail('Receiver stopped with exit code '+str(process.returncode))
      try:
       with socket.create_connection((config['host'],config['port']),timeout=.3):break
      except OSError:
       if time.monotonic()>deadline:self.fail('Receiver did not listen within 10 seconds')
       time.sleep(.05)
     settings=b'capture-settings-v1\nsource=generated-setup-test\n';image=b'unchanged local test image'
     meta=dict(version=1,device_id=config['device_id'],boot_id='test-boot',capture_us=123,capture_utc=None,image_sha256=digest(image),image_bytes=len(image),firmware_sha256='1'*64,model_sha256='2'*64,calibration_sha256='3'*64,settings_sha256=digest(settings))
     def post(path,data,headers,credential=token,context=trust):
      conn=http.client.HTTPSConnection(config['host'],config['port'],timeout=3,context=context)
      try:
       conn.request('POST',path,data,dict({'Authorization':'Bearer '+credential,'Content-Type':'application/octet-stream'},**headers))
       r=conn.getresponse();return r.status,json.loads(r.read())
      finally:conn.close()
     self.assertEqual(post('/v1/settings',settings,{'X-Settings-SHA256':digest(settings)},'wrong-token')[0],401)
     self.assertFalse(archive.exists())
     with self.assertRaises(ssl.SSLCertVerificationError):post('/v1/settings',settings,{},context=ssl.create_default_context())
     self.assertFalse(archive.exists())
     self.assertEqual(post('/v1/settings',settings,{'X-Settings-SHA256':digest(settings)})[0],201)
     headers={'X-Meter-Metadata':base64.b64encode(canonical(meta)).decode()}
     status,receipt=post('/v1/captures',image,headers);self.assertEqual(status,201)
     self.assertEqual((archive/'blobs'/f'{digest(image)}.image').read_bytes(),image)
     self.assertTrue(receipt['verified_readback']);self.assertFalse(receipt['training_eligible'])
     self.assertEqual(receipt['review_status'],'unreviewed')
     record=(archive/'captures'/f'{receipt["capture_id"]}.json').read_bytes();self.assertEqual(digest(record),receipt['record_sha256'])
     self.assertEqual(post('/v1/captures',image,headers)[0],200)
     self.assertEqual(len(list((archive/'captures').iterdir())),1)
    finally:
     if process.poll() is None:process.terminate()
     try:process.wait(timeout=5)
     except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
if __name__=='__main__':unittest.main()
