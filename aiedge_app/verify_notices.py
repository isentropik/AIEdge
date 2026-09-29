"""Verify retained notice provenance against the pinned Linux wheel lock."""
import hashlib,json,re
from pathlib import Path

def normalized(name):return re.sub(r'[-_.]+','-',name).lower()

def verify(root=None):
    root=Path(root or Path(__file__).parent)
    expected={}
    for line in (root/'requirements-linux-amd64.lock').read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.startswith('#'):continue
        match=re.fullmatch(r'([A-Za-z0-9_.-]+)==([^ ]+) --hash=sha256:([a-f0-9]{64})',line)
        if not match:raise ValueError('invalid_dependency_lock')
        name,version,digest=match.groups();expected[normalized(name)]=(version,digest)
    manifest=json.loads((root/'third-party/manifest.json').read_text(encoding='utf-8'))
    actual={};files=set()
    for package in manifest['packages']:
        name=normalized(package['name'])
        if name in actual:raise ValueError('duplicate_notice_package')
        actual[name]=(package['version'],package['wheel_sha256'])
        if not package['notices']:raise ValueError('missing_package_notice')
        for notice in package['notices']:
            filename=notice['file']
            if not re.fullmatch(r'[A-Za-z0-9_.-]+\.txt',filename):raise ValueError('invalid_notice_path')
            if hashlib.sha256((root/'third-party'/filename).read_bytes()).hexdigest()!=notice['sha256']:
                raise ValueError('notice_hash_mismatch')
            if not notice.get('source'):raise ValueError('notice_source_missing')
            files.add(filename)
    if actual!=expected:raise ValueError('notices_do_not_match_dependency_lock')
    return {'packages':len(actual),'notice_texts':len(files),'complete_distribution_review':False}

if __name__=='__main__':print(json.dumps(verify(),sort_keys=True))
