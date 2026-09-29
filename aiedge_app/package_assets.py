"""Verify the self-contained native/model assets before container compilation."""
import hashlib,json
from pathlib import Path

def verify(directory):
    root=Path(directory).resolve()
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('version')!=1:raise ValueError('unsupported_asset_manifest')
    files=manifest['files']
    for name,digest in files.items():
        path=root/name
        if Path(name).is_absolute() or '..' in Path(name).parts or not path.resolve().is_relative_to(root):raise ValueError('invalid_asset_path')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('asset_hash_mismatch:'+name)
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name!='manifest.json'}
    if actual!=set(files):raise ValueError('unexpected_asset_files')
    return manifest

if __name__=='__main__':
    verify(Path(__file__).parent/'assets')
    print('Packaged native headers, models and attribution verified.')
