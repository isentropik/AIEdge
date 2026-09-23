"""Compact versioned asset contract for the custom updater (not a signature)."""
import hashlib
import json
import struct

def digest(data):return hashlib.sha256(data).hexdigest()
def esp32_app_digest(image):
 # Scope: unsigned classic ESP32 application with appended SHA-256.
 # SDK must still validate load addresses, chip revision and image at OTA time.
 if len(image)<24 or image[0]!=0xe9 or not 1<=image[1]<=16 or image[23]!=1 or struct.unpack_from('<H',image,12)[0]!=0:
  raise ValueError('Unsupported ESP32 application format')
 offset=24;checksum=0xef
 for _ in range(image[1]):
  if offset+8>len(image):raise ValueError('Truncated segment header')
  _,length=struct.unpack_from('<II',image,offset);offset+=8
  if length>len(image)-offset:raise ValueError('Truncated segment')
  for value in image[offset:offset+length]:checksum^=value
  offset+=length
 end=(offset//16+1)*16
 if end+32!=len(image) or any(image[offset:end-1]) or image[end-1]!=checksum:
  raise ValueError('Invalid checksum, padding or trailing content')
 actual=hashlib.sha256(image[:end]).digest()
 if image[end:]!=actual:raise ValueError('Application digest mismatch')
 return actual.hex()

def make_device_manifest(files,expected_model,boot_policy="optional_bundle"):
 if boot_policy not in ("required_bundle","optional_bundle"):raise ValueError("Unknown boot policy")
 image=files['firmware/firmware.bin']
 if digest(files['model/polar-int8.tflite'])!=expected_model:raise ValueError('Model identity mismatch')
 assets={name:{'bytes':len(data),'sha256':digest(data)} for name,data in sorted(files.items())
         if name.startswith(('html/','model/','diagnostics/'))}
 if 'html/index.html' not in assets or 'diagnostics/polar-runtime-vectors.bin' not in assets:raise ValueError('Missing required runtime asset')
 result={'format':'meter-bundle-v2','boot_policy':boot_policy,'chip':'esp32','firmware':{'path':'firmware/firmware.bin',
   'bytes':len(image),'sha256':digest(image),'app_image_sha256':esp32_app_digest(image)},
   'model_sha256':expected_model,'assets':assets}
 # The contract ID binds app and all runtime assets; not deployment authorization.
 canonical=json.dumps(result,sort_keys=True,separators=(',',':')).encode('ascii')
 result['bundle_id']=digest(canonical)
 return json.dumps(result,sort_keys=True,separators=(',',':')).encode('ascii')
