"""Create a new development bundle from a hash-verified seed and ESP32 app."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
from device_bundle_manifest import make_device_manifest

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seed',type=Path,required=True)
    p.add_argument('--seed-sha256',required=True)
    p.add_argument('--firmware',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--without-diagnostics',action='store_true',help='Exclude replay images and vectors; requires an application/updater that accepts optional diagnostics')
    a=p.parse_args()
    if a.output.exists():p.error('Output already exists; choose a new path')
    if hashlib.sha256(a.seed.read_bytes()).hexdigest()!=a.seed_sha256:
        p.error('Seed ZIP hash mismatch')
    with zipfile.ZipFile(a.seed) as z:
        manifest=json.loads(z.read('device-manifest.json'))
        files={}
        for name,expected in manifest['assets'].items():
            if not name.startswith(('html/','model/','diagnostics/')) or '..' in name.split('/') or '\\' in name:
                p.error('Invalid asset path')
            data=z.read(name)
            if len(data)!=expected['bytes'] or hashlib.sha256(data).hexdigest()!=expected['sha256']:
                p.error('Seed asset mismatch: '+name)
            if not (a.without_diagnostics and name.startswith('diagnostics/')):
                files[name]=data
        for name in ['docs/Licence.md','README.txt']:
            if name in z.namelist():files[name]=z.read(name)
    files['firmware/firmware.bin']=a.firmware.read_bytes()
    files['device-manifest.json']=make_device_manifest(files,manifest['model_sha256'],'required_bundle')
    with zipfile.ZipFile(a.output,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for name,data in sorted(files.items()):z.writestr(name,data)
    m=json.loads(files['device-manifest.json'])
    result={'zip_sha256':hashlib.sha256(a.output.read_bytes()).hexdigest(),
            'bytes':a.output.stat().st_size,'bundle_id':m['bundle_id'],
            'model_sha256':m['model_sha256'],'boot_policy':'required_bundle',
            'deployed':False,'recognition_revalidated':False,
            'diagnostics_included':any(n.startswith('diagnostics/') for n in files)}
    a.output.with_suffix('.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
