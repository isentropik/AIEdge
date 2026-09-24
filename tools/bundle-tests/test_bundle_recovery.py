"""Real bundle verifier/stager/index regressions; synthetic temporary files only."""
import argparse, hashlib, json, os, struct, subprocess, sys, tempfile, zipfile
from pathlib import Path

if not __debug__:
    raise SystemExit('Run without -O: regression assertions must remain enabled.')
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/aiedge'))
from device_bundle_manifest import make_device_manifest,digest
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--idf',type=Path,default=os.environ.get('IDF_PATH'),
                    help='ESP-IDF framework root containing components/mbedtls and components/json')
args=parser.parse_args()
if not args.idf:parser.error('Provide --idf or IDF_PATH; no SDK is downloaded automatically.')
SDK=args.idf.resolve()/'components';TLS=SDK/'mbedtls/mbedtls';JSON=SDK/'json/cJSON'
OTA=ROOT/'code/components/jomjol_fileserver_ota'
FLOW=ROOT/'code/components/jomjol_flowcontroll'
for dependency in [TLS/'library/sha256.c',JSON/'cJSON.c',OTA/'miniz/miniz.c']:
    if not dependency.is_file():parser.error('Missing dependency: '+str(dependency))
if os.name=='nt':
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(0x0001|0x0002)
work=tempfile.TemporaryDirectory(prefix='aiedge-bundle-tests-')
OUT=Path(work.name)

def synthetic_image():
    header=bytearray(24);header[0]=0xe9;header[1]=1;header[23]=1
    data=b'payload';raw=bytes(header)+struct.pack('<II',0x3ffb0000,len(data))+data
    checksum=0xef
    for byte in data:checksum^=byte
    raw+=bytes((16-(len(raw)+1)%16)%16)+bytes([checksum])
    return raw+hashlib.sha256(raw).digest()

(OUT/'config.h').write_text('#define MBEDTLS_SHA256_C\n#define MBEDTLS_PLATFORM_C\n')
source=OUT/'test.cpp';source.write_text(r"""
#include <unistd.h>
#ifdef _WIN32
#include <io.h>
#endif
static bool failSync=false;
static int testSync(int fd){
 if(failSync)return -1;
#ifdef _WIN32
 return _commit(fd);
#else
 return fsync(fd);
#endif
}
#define fsync testSync
#include "ManagedBundleTransaction.h"
#ifdef _WIN32
#include <direct.h>
#define mkdir(path,mode) _mkdir(path)
#endif
#include "StageDeviceBundle.h"
#undef mkdir
#undef fsync
#include "BundleSelection.h"
#include "ImageArchiveSha.h"
#include <cassert>
#include <iostream>
struct FakeFlash {
 std::string hash;int mode=0,calls=0,boots=0;
 bool writeAndSelect(const std::string& path,std::function<bool(const std::string&)> prepare){
  ++calls;assert(path.find("/firmware/firmware.bin")!=std::string::npos);
  if(mode==1)return false;
  if(!prepare(mode==2?std::string(64,'f'):hash))return false;
  if(mode==3)return false;
  ++boots;return true;
 }
};
int main(int argc,char** argv){
 if(argc==4){
  MeterBundle::File expected;expected.bytes=1;expected.hash=argv[2];
  auto trace=[](const char* step,const char* path,uint64_t detail){std::cerr<<step<<" "<<path<<" "<<detail<<"\n";};
  std::cout<<MeterBundle::verifyFile<ImageArchive::Sha256>(argv[1],expected,trace)<<"\n";return 0;
 }

 {static unsigned reports=0;int cookie=7;
  auto read=[](void* context,mz_uint64 offset,void* buffer,size_t bytes)->size_t{assert(*static_cast<int*>(context)==7&&offset==123&&bytes==10);*static_cast<char*>(buffer)='x';errno=EIO;return 4;};
  auto trace=[](const char* step,const char* path,uint64_t detail){assert(std::string(path)=="test.zip");
   const char* expected[]={"archive.read_failed.offset","archive.read_failed.requested","archive.read_failed.returned","archive.read_failed.errno"};
   const uint64_t values[]={123,10,4,EIO};assert(reports<4&&std::string(step)==expected[reports]&&detail==values[reports]);++reports;errno=EINVAL;};
  MeterBundle::ArchiveReadDiagnostic diagnostic{read,&cookie,trace,"test.zip"};char buffer[10]{};
  assert(MeterBundle::ArchiveReadDiagnostic::read(&diagnostic,123,buffer,10)==4&&buffer[0]=='x'&&errno==EIO&&reports==4);
 }
 if(argc==9){failSync=std::string(argv[5])=="fail_sync";
  auto trace=[](const char* step,const char* path,uint64_t detail){std::cerr<<step<<" "<<path<<" "<<detail<<"\n";};
  std::cout<<static_cast<int>(MeterBundle::stageZip<ImageArchive::Sha256>(argv[1],argv[2],argv[3],argv[4],trace))<<"\n";
  return 0;
 }

 if(argc==8){FakeFlash flash;flash.hash=argv[5];flash.mode=std::atoi(argv[6]);
  bool ok=MeterBundle::install<ImageArchive::Sha256>(argv[1],argv[2],argv[3],argv[4],flash);
  std::cout<<ok<<","<<flash.calls<<","<<flash.boots<<"\n";return 0;
 }

 if(argc==7){failSync=std::string(argv[5])=="fail_sync";
  std::cout<<static_cast<int>(MeterBundle::prepareIndex<ImageArchive::Sha256>(argv[1],argv[2],argv[3],argv[4]))<<"\n";
  return 0;
 }

 if(argc==6){MeterBundle::Selection selection;
  bool ok=selection.loadForApp<ImageArchive::Sha256>(argv[1],argv[2],argv[3],std::string(argv[4])=="1");
  const int state=static_cast<int>(selection.state());
  assert(!selection.loadForApp<ImageArchive::Sha256>(argv[1],argv[2],argv[3],false));
  assert(static_cast<int>(selection.state())==state);
  if(state==1)assert(selection.legacyPath("/sdcard/html/index.html").empty());
  std::cout<<ok<<","<<state<<"\n";return 0;
 }
 assert(argc==3);MeterBundle::Manifest manifest;manifest.id="stale";
 const auto result=MeterBundle::verify<ImageArchive::Sha256>(argv[1],argv[2],manifest);
 if(!result.verified)assert(manifest.id.empty()&&manifest.assets.empty());
 else assert(manifest.id==argv[2]&&result.files==5&&result.failedPath.empty());
 if(result.verified){
  MeterBundle::Selection selected;
  assert(selected.resolve("html/index.html","old/index.html")=="old/index.html");
  assert(selected.load<ImageArchive::Sha256>(argv[1],argv[2],manifest.appHash,manifest.modelHash));
  assert(selected.state()==MeterBundle::SelectionState::Selected&&selected.id()==argv[2]);
  assert(selected.resolve("html/index.html","old")==std::string(argv[1])+"/html/index.html");
  assert(selected.resolve("html/missing.html","old").empty());
  assert(selected.legacyPath("/sdcard/html/index.html")==std::string(argv[1])+"/html/index.html");
  assert(selected.legacyPath("/sdcard/html/index.html.gz").empty());
  assert(selected.legacyPath("/sdcard/html/../config/config.ini").empty());
  assert(selected.legacyPath("/sdcard/config/polar-int8.tflite")==std::string(argv[1])+"/model/polar-int8.tflite");
  assert(selected.legacyPath("/sdcard/config/polar-runtime-vectors.bin")==std::string(argv[1])+"/diagnostics/polar-runtime-vectors.bin");
  assert(selected.legacyPath("/sdcard/config/polar-runtime-frame.rgb")==std::string(argv[1])+"/diagnostics/polar-runtime-frame.rgb");
  assert(selected.legacyPath("/sdcard/config/config.ini")=="/sdcard/config/config.ini");
  assert(selected.legacyPath("/sdcard/img_tmp/alg.jpg")=="/sdcard/img_tmp/alg.jpg");

  assert(selected.resolve("html/../index.html","old").empty());
  assert(!selected.load<ImageArchive::Sha256>(argv[1],argv[2],manifest.appHash,manifest.modelHash));
  assert(selected.state()==MeterBundle::SelectionState::Selected);
  for(int i=0;i<2;++i){MeterBundle::Selection rejected;
   assert(!rejected.load<ImageArchive::Sha256>(argv[1],argv[2],i?manifest.appHash:std::string(64,'0'),i?std::string(64,'0'):manifest.modelHash));
   assert(rejected.state()==MeterBundle::SelectionState::Rejected);
   assert(rejected.resolve("html/index.html","old").empty());
   assert(!rejected.load<ImageArchive::Sha256>(argv[1],argv[2],manifest.appHash,manifest.modelHash));
  }
 }

 std::cout<<result.verified<<"\n";}
""")
env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(OUT/'zig-global-cache'),ZIG_LOCAL_CACHE_DIR=str(OUT/'zig-local-cache'))
zig=[sys.executable,'-m','ziglang'];flags=['-O2','-UNDEBUG','-I'+str(OUT),'-I'+str(TLS/'include'),'-I'+str(JSON),'-I'+str(OTA),'-I'+str(FLOW),'-DMBEDTLS_CONFIG_FILE="config.h"']
objects=[]
for name,path in [(n,TLS/'library'/f'{n}.c') for n in ['sha256','platform_util','platform']]+[('cjson',JSON/'cJSON.c'),('miniz',OTA/'miniz/miniz.c')]:
 obj=OUT/(name+'.o');objects.append(str(obj));subprocess.run(zig+['cc']+flags+['-c',str(path),'-o',str(obj)],env=env,check=True)
exe=OUT/'test.exe';subprocess.run(zig+['c++','-std=c++11']+flags+[str(source)]+objects+['-o',str(exe)],env=env,check=True)
files={'firmware/firmware.bin':synthetic_image(),'model/polar-int8.tflite':b'model'*1500,'html/index.html':b'page','diagnostics/polar-runtime-vectors.bin':b'vectors','diagnostics/polar-runtime-frame.rgb':b'RGB'}
raw=make_device_manifest(files,digest(files['model/polar-int8.tflite']),"required_bundle");identity=json.loads(raw)['bundle_id'];files['device-manifest.json']=raw
cases=0
with tempfile.TemporaryDirectory() as folder:
 root=Path(folder)
 for name,data in files.items():p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 def check(ok,id=identity):
  global cases
  before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
  result=subprocess.run([str(exe),folder,id],text=True,capture_output=True,check=True)
  assert result.stdout.strip()==str(int(ok)),result.stdout
  assert before=={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
  cases+=1
 check(True);check(False,'0'*64);check(False,'invalid')
 for name,data in files.items():
  p=root/name
  for changed in [data[:-1],data+b'X',bytes([data[0]^1])+data[1:]]:
   p.write_bytes(changed);check(False)
  p.unlink();check(False);p.write_bytes(data)
 check(True)
print(f'{cases} streamed bundle verification cases passed with real SHA/readback; no mutations')

# Exact early verification errors, with real files and no verifier mutations.
with tempfile.TemporaryDirectory() as folder:
 p=Path(folder)/'probe'
 def probe(expected,step):
  result=subprocess.run([str(exe),str(p),hashlib.sha256(b'a').hexdigest(),'file'],text=True,capture_output=True,check=True)
  assert result.stdout.strip()==str(expected) and step in result.stderr,result.stderr
 probe(0,'verify.stat_failed')
 p.mkdir();probe(0,'verify.type_failed');p.rmdir()
 p.write_bytes(b'aa');probe(0,'verify.size_failed');assert p.read_bytes()==b'aa'
 p.write_bytes(b'b');probe(0,'verify.fail');assert p.read_bytes()==b'b'
 p.write_bytes(b'a');probe(1,'verify.pass');assert p.read_bytes()==b'a'
print('5 precise file-verification diagnostic cases passed')

# Separate boot index fixtures; all calls are read-only, including missing index.
boot_cases=0
with tempfile.TemporaryDirectory() as folder:
 root=Path(folder);manifest=json.loads(raw);app=manifest['firmware']['app_image_sha256'];model=manifest['model_sha256']
 obj=root/'objects'/identity
 for name,data in files.items():
  p=obj/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 index=root/'apps'/(app+'.id');index.parent.mkdir()
 def boot(expected,required=True,app_id=app):
  global boot_cases
  before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
  result=subprocess.run([str(exe),folder,app_id,model,str(int(required)),'boot'],text=True,capture_output=True,check=True)
  assert result.stdout.strip()==expected,result.stdout
  assert before=={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
  boot_cases+=1
 boot('1,0',False);boot('0,1',True)
 for data in [identity.encode(),(identity+'\n').encode()]:
  index.write_bytes(data);boot('1,2')
 for data in [b'',b'X'*64,(identity+'\r\n').encode(),(identity+'X').encode(),b'0'*64,identity[:63].encode()]:
  index.write_bytes(data);boot('0,1');boot('0,1',False)
 index.unlink();index.mkdir();boot('0,1');index.rmdir()
 index.write_text(identity);boot('0,1',app_id='../bad')
 model_file=obj/'model/polar-int8.tflite';model_file.write_bytes(b'damaged');boot('0,1')
print(f'{boot_cases} application-keyed boot selection cases passed; no writes or legacy fallback on invalid index')

install_cases=0
with tempfile.TemporaryDirectory() as folder:
 root=Path(folder); obj=root/'objects'/identity
 for name,data in files.items():
  p=obj/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 (root/'apps').mkdir();app=json.loads(raw)['firmware']['app_image_sha256'];model=json.loads(raw)['model_sha256']
 index=root/'apps'/(app+'.id');pending=Path(str(index)+'.pending')
 def install(expected,running='0'*64,expected_model=model,mode='ok'):
  global install_cases
  before={str(p.relative_to(obj)):p.read_bytes() for p in obj.rglob('*') if p.is_file()}
  result=subprocess.run([str(exe),folder,identity,running,expected_model,mode,'install'],text=True,capture_output=True,check=True)
  assert result.stdout.strip()==str(expected),result.stdout
  assert before=={str(p.relative_to(obj)):p.read_bytes() for p in obj.rglob('*') if p.is_file()}
  install_cases+=1
 install(0,running=app);assert not index.exists() and not pending.exists()
 install(0,expected_model='0'*64);assert not index.exists()
 install(2,mode='fail_sync');assert pending.exists() and not index.exists()
 original_pending=pending.read_bytes()
 install(4);assert not pending.exists() and index.read_text()==identity+'\n'
 assert Path(str(pending)+'.interrupted-0').read_bytes()==original_pending
 index.unlink() # host fixture only: independently test conflicting final mappings
 index.write_text('f'*64);install(1);assert index.read_text()=='f'*64
 index.unlink();install(4);assert index.read_bytes()==(identity+'\n').encode() and not pending.exists()
 install(3);assert index.read_bytes()==(identity+'\n').encode()
 for slot,bad in enumerate([b'partial',b'f'*64+b'\n',b'x'*80],start=1):
  index.unlink() # host fixture only
  pending.write_bytes(bad)
  install(4)
  assert Path(str(pending)+'.interrupted-'+str(slot)).read_bytes()==bad
  assert index.read_text()==identity+'\n'
 index.unlink() # host fixture only
 for slot in range(4,32):Path(str(pending)+'.interrupted-'+str(slot)).write_bytes(b'preserved')
 pending.write_bytes(b'last-partial');install(1)
 assert pending.read_bytes()==b'last-partial' and not index.exists()
 pending.unlink() # host fixture only
 pending.mkdir();install(1);assert pending.is_dir();pending.rmdir()
 install(4)
 model_file=obj/'model/polar-int8.tflite';model_file.write_bytes(b'bad')
 install(0);assert index.read_bytes()==(identity+'\n').encode()
print(f'{install_cases} index publication cases passed; sync failures preserved, existing mappings protected')

transaction_cases=0
with tempfile.TemporaryDirectory() as folder:
 root=Path(folder);obj=root/'objects'/identity
 for name,data in files.items():
  p=obj/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 (root/'apps').mkdir();app=json.loads(raw)['firmware']['app_image_sha256'];model=json.loads(raw)['model_sha256']
 index=root/'apps'/(app+'.id')
 def transact(expected,mode=0,running='0'*64,bundle_id=identity):
  global transaction_cases
  result=subprocess.run([str(exe),folder,bundle_id,running,model,app,str(mode),'transaction'],text=True,capture_output=True,check=True)
  assert result.stdout.strip()==expected,result.stdout
  transaction_cases+=1
 optional_raw=make_device_manifest(files,model,"optional_bundle")
 optional_id=json.loads(optional_raw)['bundle_id']
 for name,data in dict(files,**{'device-manifest.json':optional_raw}).items():
  p=root/'objects'/optional_id/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 transact('0,0,0',bundle_id=optional_id);assert not index.exists()
 transact('0,0,0',running=app);assert not index.exists()
 transact('0,1,0',mode=1);assert not index.exists()
 transact('0,1,0',mode=2);assert not index.exists()
 index.write_text('e'*64);transact('0,1,0');assert index.read_text()=='e'*64
 index.unlink();transact('0,1,0',mode=3);assert index.read_text()==identity+'\n'
 transact('1,1,1');assert index.read_text()==identity+'\n'
 (obj/'html/index.html').write_bytes(b'changed');transact('0,0,0')
print(f'{transaction_cases} managed transaction cases passed; mismatched flash never selects boot')

stage_cases=0
with tempfile.TemporaryDirectory() as folder:
 root=Path(folder);archive=root/'candidate.zip';model=json.loads(raw)['model_sha256']
 def write_zip(values):
  with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
   for name,data in values:z.writestr(name,data)
 def stage(expected,name,mode='ok',bundle_id=identity):
  global stage_cases
  base=root/name
  result=subprocess.run([str(exe),str(archive),str(base),bundle_id,model,mode,'stage','x','x'],text=True,capture_output=True,check=True)
  assert result.stdout.strip()==str(expected),result.stdout
  if mode=='fail_sync':assert 'extract.sync_failed' in result.stderr,result.stderr
  if name=='hashfail':assert 'extract.integrity_failed' in result.stderr,result.stderr
  if name=='blockedbase':assert any(step in result.stderr for step in ['object.stat_failed','directory.type_failed']),result.stderr
  if name=='blockedapps':assert 'directory.type_failed' in result.stderr,result.stderr
  stage_cases+=1
  return base
 write_zip(list(files.items()))
 (root/'blockedbase').write_bytes(b'preserve')
 stage(1,'blockedbase');assert (root/'blockedbase').read_bytes()==b'preserve'
 (root/'blockedapps').mkdir();(root/'blockedapps/apps').write_bytes(b'preserve')
 stage(1,'blockedapps');assert (root/'blockedapps/apps').read_bytes()==b'preserve'
 assert not (root/'blockedapps/pending'/identity).exists()
 write_zip(list(files.items())+[('docs/ignored.txt',b'not a runtime asset')])
 base=stage(4,'good');stage(3,'good')
 assert not (base/'objects'/identity/'docs').exists()
 assert not list((base/'apps').iterdir())
 for name,data in files.items():assert (base/'objects'/identity/name).read_bytes()==data
 assert not (base/'pending'/identity).exists()
 stage(0,'badid',bundle_id='0'*64);assert not (root/'badid').exists()
 failed=stage(1,'syncfail',mode='fail_sync');assert (failed/'pending'/identity).is_dir()
 retained={str(p.relative_to(failed/'pending'/identity)):p.read_bytes() for p in (failed/'pending'/identity).rglob('*') if p.is_file()}
 stage(4,'syncfail');assert (failed/'objects'/identity).exists()
 saved=failed/'interrupted'/(identity+'-0')
 assert retained=={str(p.relative_to(saved)):p.read_bytes() for p in saved.rglob('*') if p.is_file()}
 for name,data in files.items():assert (failed/'objects'/identity/name).read_bytes()==data
 for i,(name,data) in enumerate([('../escape',b'x'),('HTML/INDEX.HTML',b'x'),('html/index.html/sub',b'x')]):
  write_zip(list(files.items())+[(name,data)]);stage(0,'unsafe'+str(i));assert not (root/('unsafe'+str(i))).exists()
 altered=dict(files);altered['html/index.html']=b'xxxx';write_zip(list(altered.items()))
 failed=stage(1,'hashfail');assert not (failed/'objects'/identity).exists()
 missing=dict(files);del missing['html/index.html'];write_zip(list(missing.items()));stage(0,'missing')
 optional=make_device_manifest(files,model,'optional_bundle');altered=dict(files);altered['device-manifest.json']=optional
 write_zip(list(altered.items()));stage(0,'bootstrap',bundle_id=json.loads(optional)['bundle_id'])
 write_zip(list(files.items())+[('docs/too-big',b'x'*(2*1024*1024+1))]);stage(0,'oversized')
 write_zip(list(files.items()));archive.write_bytes(archive.read_bytes()[:-22]);stage(0,'truncated')
print(f'{stage_cases} actual miniz staging cases passed; prior objects preserved, no app index or flash changes')


work.cleanup()
