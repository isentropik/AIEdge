"""Generate matching firmware/web build identity without modifying source files."""
import argparse, datetime, json, os, subprocess
from pathlib import Path

def generate(repo, output, epoch=None):
    repo, output = Path(repo).resolve(), Path(output)
    def git(*args):
        try: result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)
        except OSError: return None
        return result.stdout.strip() if result.returncode == 0 else None
    # A downloaded source archive must not inherit an unrelated parent checkout.
    top = git('rev-parse', '--show-toplevel')
    owned = top is not None and Path(top).resolve() == repo
    revision = git('rev-parse', '--short=12', 'HEAD') if owned else None
    branch = git('branch', '--show-current') if owned else None
    status = git('status', '--porcelain', '--untracked-files=normal') if owned else None
    if revision and status: revision += '-dirty'
    elif revision and status is None: revision += '-state-unknown'
    revision = revision or 'source-archive'
    branch = branch or ('detached' if owned else 'source-archive')
    version = (repo / 'code/APP_VERSION').read_text(encoding='utf-8').strip()
    if not version or any(c not in '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-' for c in version):
        raise ValueError('Invalid APP_VERSION')
    now = datetime.datetime.fromtimestamp(int(epoch), datetime.timezone.utc) if epoch is not None else datetime.datetime.now(datetime.timezone.utc)
    metadata = {'version': 'AIEdge '+version, 'revision': revision, 'branch': branch,
                'built_at': now.strftime('%Y-%m-%d %H:%M:%S UTC')}
    output.mkdir(parents=True, exist_ok=True)
    files = {'version.cpp': ''.join('const char* '+name+'='+json.dumps(value)+';\n' for name,value in [('GIT_REV',revision),('GIT_TAG',metadata['version']),('GIT_BRANCH',branch),('BUILD_TIME',metadata['built_at'])]),
             'version.txt': metadata['version']+' (Commit: '+revision+')\n'+revision+'\n',
             'build-metadata.json': json.dumps(metadata,indent=2)+'\n'}
    for name, data in files.items():
        path = output/name
        if path.exists() and path.read_text(encoding='utf-8') == data: continue
        temporary = path.with_suffix(path.suffix+'.tmp')
        temporary.write_text(data, encoding='utf-8', newline='\n'); os.replace(temporary,path)
    return metadata

if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--repo',required=True); parser.add_argument('--output',required=True)
    args=parser.parse_args(); generate(args.repo,args.output,os.environ.get('SOURCE_DATE_EPOCH'))
