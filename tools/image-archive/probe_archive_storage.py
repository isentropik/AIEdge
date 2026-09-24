"""Test archive file operations in a new subfolder; never change existing files."""
import argparse,json,os,uuid
from pathlib import Path
from image_archive_store import write_immutable,ArchiveConflict,digest

def probe(folder):
 folder=Path(folder)
 if not folder.is_dir() or folder.is_symlink():raise ValueError('Choose an existing accessible directory, not a symbolic link')
 target=folder/('aiedge-storage-probe-'+uuid.uuid4().hex)
 target.mkdir(mode=0o700,exist_ok=False)
 report={'version':1,'probe_folder':str(target),'passed':False,'checks':[],
         'directory_sync_supported':os.name=='posix','power_loss_durability_verified':False,
         'limits':['Tests current process access only; receiver service credentials may differ.','No network upload, real image, training data or device setting is involved.','Success does not prove network-share or controller power-loss durability.','Probe files are retained in the new subfolder; existing files are untouched.']}
 try:
  payload=os.urandom(4096);file=target/'objects'/'test.bin'
  if write_immutable(file,payload) is not True:raise ValueError('New object not created')
  report['checks'].append('create_flush_publish_readback')
  if write_immutable(file,payload) is not False:raise ValueError('Identical retry not recognized')
  report['checks'].append('identical_retry')
  try:write_immutable(file,b'changed')
  except ArchiveConflict:pass
  else:raise ValueError('Conflicting content was not rejected')
  if file.read_bytes()!=payload:raise ValueError('Original content changed')
  report['checks'].append('conflict_preserves_original')
  if list((target/'objects').glob('.pending-*')):raise ValueError('Unexpected temporary files remain')
  report.update(passed=True,payload_sha256=digest(payload))
 except (OSError,ValueError) as exc:
  report['failure']={'type':type(exc).__name__,'errno':getattr(exc,'errno',None)}
 # A failed disk may prevent saving this report; callers must treat that as failure.
 with (target/'result.json').open('x',encoding='utf-8') as stream:json.dump(report,stream,indent=2)
 return report

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);a=p.parse_args()
 try:result=probe(a.folder)
 except (OSError,ValueError) as exc:p.exit(2,type(exc).__name__+': storage probe could not complete\n')
 print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)
if __name__=='__main__':main()
