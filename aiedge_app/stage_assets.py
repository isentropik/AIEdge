"""Refresh app assets from shared firmware headers and an explicit verified model folder."""
import argparse,ast,hashlib,json,re,sys
from pathlib import Path
from package_assets import verify

def stage(models,check=False):
    app=Path(__file__).resolve().parent;repo=app.parent
    shared=repo/'code/components/jomjol_tfliteclass';assets=app/'assets'
    contents={};pending=['PolarUserMarkers.h','PolarPipeline.h','PolarDecoder.h','RevolutionReading.h','RevolutionAccounting.h']
    while pending:
        name=pending.pop()
        if 'include/'+name in contents:continue
        if Path(name).name!=name:raise ValueError('nonportable_header:'+name)
        blob=(shared/name).read_bytes();contents['include/'+name]=blob
        pending.extend(re.findall(r'^\s*#include\s+"([^"\n]+)"',blob.decode('utf-8'),re.M))
    tree=ast.parse((app/'reader.py').read_text(encoding='utf-8'))
    expected=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='MODELS' for t in n.targets))
    for name,digest in expected.values():
        blob=(Path(models)/name).read_bytes()
        if hashlib.sha256(blob).hexdigest()!=digest:raise ValueError('model_hash_mismatch:'+name)
        contents['models/'+name]=blob
    for name in ('Licence.md','CREDITS.md'):contents[name]=(repo/name).read_bytes()
    manifest={'version':1,'files':{name:hashlib.sha256(blob).hexdigest() for name,blob in sorted(contents.items())},'model_source':'Exact models pinned in reader.py. Headers retain the legacy frozen calibration for parity tests; it is never activated by default. No capture archives or credentials are packaged.'}
    if check:
        if verify(assets)!=manifest:raise ValueError('packaged_assets_out_of_date')
        return
    assets.mkdir(exist_ok=True)
    extras={p.relative_to(assets).as_posix() for p in assets.rglob('*') if p.is_file() and p.name!='manifest.json'}-set(contents)
    if extras:raise ValueError('remove_obsolete_assets_explicitly:'+','.join(sorted(extras)))
    for name,blob in contents.items():
        path=assets/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(blob)
    (assets/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8');verify(assets)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--models',required=True);p.add_argument('--check',action='store_true');a=p.parse_args();stage(a.models,a.check)
    print('Assets match the shared native headers and pinned models.')
