"""Export an already tested bundle without development reports or fixtures.

Runtime assets are retained byte-for-byte; this is not a general privacy scanner.
Review their content before publishing. No network requests or deployment.
"""
import argparse,json,zipfile
from pathlib import Path
from device_bundle_manifest import digest,make_device_manifest

def export_package(seed, expected_sha, output):
    raw=seed.read_bytes()
    if digest(raw)!=expected_sha:raise ValueError('Seed ZIP hash mismatch')
    if output.exists():raise ValueError('Output already exists')
    with zipfile.ZipFile(seed) as z:
        names=z.namelist()
        if len(names)!=len(set(names)):raise ValueError('Duplicate ZIP entries')
        manifest_raw=z.read('device-manifest.json')
        manifest=json.loads(manifest_raw)
        if manifest['boot_policy']!='required_bundle':raise ValueError('Managed bundle required')
        files={'firmware/firmware.bin':z.read('firmware/firmware.bin')}
        for name in manifest['assets']:
            if not name.startswith(('html/','model/')) or any(part in ('','..','.') for part in name.split('/')) or '\\' in name or ':' in name:
                raise ValueError('Runtime export refuses diagnostic or invalid assets: '+name)
            files[name]=z.read(name)
        canonical=make_device_manifest(files,manifest['model_sha256'],'required_bundle')
        if json.loads(canonical)!=manifest:raise ValueError('Runtime manifest verification failed')
        files['device-manifest.json']=manifest_raw
        files['docs/Licence.md']=z.read('docs/Licence.md')
    # All verification precedes output creation. Never silently overwrite.
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for name,data in sorted(files.items()):
            entry=zipfile.ZipInfo(name,date_time=(2026,1,1,0,0,0))
            entry.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(entry,data)
    return dict(bundle_id=manifest['bundle_id'],sha256=digest(output.read_bytes()),
                bytes=output.stat().st_size,files=len(files),runtime_unchanged=True,
                published=False,content_review_required=True)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seed',type=Path,required=True)
    p.add_argument('--seed-sha256',required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(export_package(a.seed,a.seed_sha256,a.output),indent=2))

if __name__=='__main__':main()
