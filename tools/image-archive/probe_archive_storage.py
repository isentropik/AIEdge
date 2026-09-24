"""Test archive file operations in a new subfolder; never change existing files."""
import argparse,json,os,uuid,time,threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from image_archive_store import write_immutable,ArchiveConflict,digest

def competing_writes(target):
 """Distinct synthetic writers must preserve exactly one complete object."""
 barrier=threading.Barrier(4)
 path=target/'competing.bin'
 def writer(index):
  payload=bytes([index])*4096
  barrier.wait(timeout=10)
  try:return {'writer':index,'created':write_immutable(path,payload)}
  except ArchiveConflict:return {'writer':index,'conflict':True}
  except OSError as exc:return {'writer':index,'storage_error':type(exc).__name__,'errno':exc.errno,'winerror':getattr(exc,'winerror',None)}
 with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(writer,range(4)))
 winners=[row for row in results if row.get('created') is True]
 if len(winners)!=1:raise ValueError('Competing writes did not produce exactly one successful writer')
 winner=winners[0]['writer'];original=bytes([winner])*4096
 if path.read_bytes()!=original:raise ValueError('Competing writes changed winning content')
 for index in range(4):
  if index==winner:
   if write_immutable(path,original) is not False:raise ValueError('Winning retry not recognized')
  else:
   try:write_immutable(path,bytes([index])*4096)
   except ArchiveConflict:pass
   else:raise ValueError('Losing retry was accepted')
 if path.read_bytes()!=original:raise ValueError('Retry changed winning content')
 return results

def probe(folder):
 folder=Path(folder)
 if not folder.is_dir() or folder.is_symlink():raise ValueError('Choose an existing accessible directory, not a symbolic link')
 target=folder/('aiedge-storage-probe-'+uuid.uuid4().hex)
 target.mkdir(mode=0o700,exist_ok=False)
 report={'version':1,'probe_folder':str(target),'passed':False,'checks':[],
         'directory_sync_supported':os.name=='posix','power_loss_durability_verified':False,
         'limits':['Tests current process access only; receiver service credentials may differ.','No network upload, real image, training data or device setting is involved.','Success does not prove network-share or controller power-loss durability.','Probe files are retained in the new subfolder; existing files are untouched.']}
 stage='create_flush_publish_readback';started=time.monotonic()
 try:
  payload=os.urandom(4096);file=target/'objects'/'test.bin'
  if write_immutable(file,payload) is not True:raise ValueError('New object not created')
  report['checks'].append('create_flush_publish_readback')
  stage='identical_retry'
  if write_immutable(file,payload) is not False:raise ValueError('Identical retry not recognized')
  report['checks'].append('identical_retry')
  stage='conflict_preserves_original'
  try:write_immutable(file,b'changed')
  except ArchiveConflict:pass
  else:raise ValueError('Conflicting content was not rejected')
  if file.read_bytes()!=payload:raise ValueError('Original content changed')
  report['checks'].append('conflict_preserves_original')
  stage='competing_writes_and_retry'
  report['competing_writes']=competing_writes(target/'objects')
  report['checks'].append(stage)
  stage='temporary_cleanup'
  if list((target/'objects').glob('.pending-*')):raise ValueError('Unexpected temporary files remain')
  report.update(passed=True,payload_sha256=digest(payload))
 except (OSError,ValueError) as exc:
  report['failure']={'stage':stage,'type':type(exc).__name__,'errno':getattr(exc,'errno',None),'winerror':getattr(exc,'winerror',None)}
 report['elapsed_seconds']=round(time.monotonic()-started,3)
 # A failed disk may prevent saving this report; callers must treat that as failure.
 with (target/'result.json').open('x',encoding='utf-8') as stream:json.dump(report,stream,indent=2)
 return report

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);a=p.parse_args()
 try:result=probe(a.folder)
 except (OSError,ValueError) as exc:p.exit(2,type(exc).__name__+': storage probe could not complete\n')
 print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)
if __name__=='__main__':main()
