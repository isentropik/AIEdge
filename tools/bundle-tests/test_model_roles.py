"""Test actual role loader and workspace boundaries with real model hashes.
Python with ziglang, an ESP-IDF source directory, and both model files required.
The interpreter is stubbed; SHA256 and file I/O are real.
"""
import argparse,hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
if os.name=='nt':
 import ctypes
 ctypes.windll.kernel32.SetErrorMode(0x0001|0x0002)
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--idf',required=True,type=Path);p.add_argument('--main-model',required=True,type=Path);p.add_argument('--secondary-model',required=True,type=Path)
a=p.parse_args();root=Path(__file__).resolve().parents[2];comp=root/'code/components/jomjol_tfliteclass'
from export_model_roles import generate
header,manifest=generate(a.main_model,a.secondary_model)
assert (comp/'PolarModelRoles.h').read_bytes()==header
assert (comp/'PolarModelRoles.json').read_bytes()==manifest
source=(comp/'CTfLiteClass.cpp').read_text(encoding='utf-8')
def part(start,end):return source[source.index(start):source.index(end,source.index(start))]
methods=part('void CTfLiteClass::ResetInterpreter()', 'float CTfLiteClass::GetOutputValue')
methods+=source[source.index('long CTfLiteClass::GetFileSize('):]
routing=(comp/'PolarModelRouting.h').read_text(encoding='utf-8')
routing=routing[routing.index('namespace polar {'):]
allocator=(root/'code/components/jomjol_helper/psram.cpp').read_text(encoding='utf-8')
allocator=allocator[allocator.index('void *psram_get_shared_tensor_arena_memory(void)'):allocator.index('void *malloc_psram_heap(')]
harness=r"""
#include "PolarModelRoles.h"
#include "mbedtls/sha256.h"
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>
#include <sys/stat.h>
#include <map>
const int ESP_LOG_DEBUG=0,ESP_LOG_ERROR=1,TENSOR_ARENA_SIZE=256,MAX_MODEL_SIZE=65536;
const char* TAG="test";unsigned char region[TENSOR_ARENA_SIZE+MAX_MODEL_SIZE];
void* shared_region=region;std::string sharedMemoryInUseFor;int interpreted=0,live=0,destroyed=0;
struct Logger{void WriteToFile(int,const char*,std::string){}void WriteHeapInfo(const char*){}}LogFile;
using std::to_string;
"""+allocator+r"""
namespace tflite {
struct Model{};
const Model* GetModel(unsigned char* p){++interpreted;return reinterpret_cast<const Model*>(p);}
struct MicroInterpreter{
 const unsigned char* p;unsigned char first;
 MicroInterpreter(const Model* m):p(reinterpret_cast<const unsigned char*>(m)),first(*p){assert(live==0);++live;}
 ~MicroInterpreter(){assert(*p==first);--live;++destroyed;}
};}
class CTfLiteClass {
public:
 bool allocateOk=true,contractOk=true;
 bool MakeAllocate(){return model && allocateOk;}bool HasPolarTensorContract(){return contractOk;}
 const tflite::Model* model=nullptr;tflite::MicroInterpreter* interpreter=nullptr;
 int kTensorArenaSize;uint8_t* tensor_arena=nullptr;unsigned char* modelfile=nullptr;
 size_t loadedModelBytes=0,polarWorkspaceOffset=0;bool verifiedPolarModel=false;
 float* input=nullptr;void* output=nullptr;
 CTfLiteClass();~CTfLiteClass();void ResetInterpreter();long GetFileSize(std::string);
 bool ReadFileToModel(std::string);bool LoadModel(std::string);bool LoadFrozenPolarModel(std::string);
 bool LoadPolarModel(std::string,polar::ModelRole);void* GetPolarWorkspace(size_t);
};
"""+methods+r"""
namespace MeterBundle {
struct Selection {
 std::map<std::string,std::string> assets;
 std::string resolve(const std::string& asset,const std::string& legacy){assert(legacy.empty());return assets.count(asset)?assets[asset]:legacy;}
};
Selection& bootSelection(){static Selection s;return s;}
}
"""+routing+r"""
int main(int argc,char**argv){
 assert(argc==8);std::string main=argv[1],secondary=argv[2],bad=argv[3],shortFile=argv[4],longFile=argv[5],empty=argv[6],large=argv[7];
 assert(std::string(polar::mainModel.hex)!=polar::secondaryModel.hex);
 CTfLiteClass net;
 assert(!net.GetPolarWorkspace(64));
 assert(net.LoadPolarModel(main,polar::ModelRole::Main));assert(interpreted==1);
 assert(!net.GetPolarWorkspace(0));assert(!net.GetPolarWorkspace(MAX_MODEL_SIZE));
 assert(net.polarWorkspaceOffset==0);
 auto* workspace=static_cast<unsigned char*>(net.GetPolarWorkspace(512));assert(workspace);
 assert(reinterpret_cast<uintptr_t>(workspace)%8==0);std::memset(workspace,0xa5,512);
 const auto offset=net.polarWorkspaceOffset;
 auto intact=[&](){for(int i=0;i<512;++i)assert(workspace[i]==0xa5);assert(net.polarWorkspaceOffset==offset);};
 for(int i=0;i<6;++i){
  net.interpreter=new tflite::MicroInterpreter(net.model);
  const bool toSecondary=i%2==0;
  assert(net.LoadPolarModel(toSecondary?secondary:main,toSecondary?polar::ModelRole::Secondary:polar::ModelRole::Main));
  assert(live==0&&net.verifiedPolarModel&&net.GetPolarWorkspace(512)==workspace);intact();
 }
 assert(interpreted==7&&destroyed==6);
 auto rejected=[&](const std::string& file,polar::ModelRole role){
  assert(net.LoadFrozenPolarModel(secondary));
  net.interpreter=new tflite::MicroInterpreter(net.model);
  const int before=interpreted;
  assert(!net.LoadPolarModel(file,role));
  assert(interpreted==before&&!net.model&&!net.interpreter&&!net.verifiedPolarModel);
  assert(!net.GetPolarWorkspace(512)&&live==0);intact();
 };
 rejected(secondary,polar::ModelRole::Main);rejected(main,polar::ModelRole::Secondary);
 rejected(bad,polar::ModelRole::Main);rejected(shortFile,polar::ModelRole::Main);
 rejected(longFile,polar::ModelRole::Main);rejected(empty,polar::ModelRole::Main);
 rejected(main+".missing",polar::ModelRole::Main);
 rejected(main,static_cast<polar::ModelRole>(99));
 rejected(large,polar::ModelRole::Main);
 assert(net.LoadFrozenPolarModel(secondary));assert(net.GetPolarWorkspace(512)==workspace);intact();
 // A generic small load must not move a previously borrowed workspace boundary.
 assert(net.LoadModel(empty+".small"));assert(!net.GetPolarWorkspace(512));intact();
 assert(net.LoadPolarModel(main,polar::ModelRole::Main));assert(net.GetPolarWorkspace(512)==workspace);intact();
 auto& selected=MeterBundle::bootSelection();
 assert(!polar::loadRole(net,polar::ModelRole::Main));
 selected.assets[polar::mainModel.asset]=main;selected.assets[polar::secondaryModel.asset]=secondary;
 assert(polar::validateBothRoles(net));intact();
 selected.assets[polar::mainModel.asset]=secondary;assert(!polar::validateBothRoles(net));
 selected.assets[polar::mainModel.asset]=main;selected.assets[polar::secondaryModel.asset]=main;assert(!polar::validateBothRoles(net));
 selected.assets[polar::secondaryModel.asset]=secondary;
 net.allocateOk=false;assert(!polar::loadRole(net,polar::ModelRole::Main));net.allocateOk=true;
 net.contractOk=false;assert(!polar::loadRole(net,polar::ModelRole::Main));net.contractOk=true;
 assert(!polar::loadRole(net,static_cast<polar::ModelRole>(99)));
 assert(polar::validateBothRoles(net));intact();
}
"""
with tempfile.TemporaryDirectory(prefix='aiedge-model-roles-') as temp:
 out=Path(temp);(out/'test.cpp').write_text(harness,encoding='utf-8')
 (out/'config.h').write_text('#define MBEDTLS_SHA256_C\n#define MBEDTLS_PLATFORM_C\n',encoding='utf-8')
 tls=a.idf/'components/mbedtls/mbedtls'
 env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(out/'global'),ZIG_LOCAL_CACHE_DIR=str(out/'local'))
 zig=[sys.executable,'-m','ziglang'];flags=['-O2','-UNDEBUG','-I'+str(out),'-I'+str(comp),'-I'+str(tls/'include'),'-DMBEDTLS_CONFIG_FILE="config.h"']
 objects=[]
 for name in ['sha256','platform_util','platform']:
  obj=out/(name+'.o');objects.append(str(obj));subprocess.run(zig+['cc']+flags+['-c',str(tls/'library'/f'{name}.c'),'-o',str(obj)],env=env,check=True)
 exe=out/'test.exe';subprocess.run(zig+['c++','-std=c++11']+flags+[str(out/'test.cpp')]+objects+['-o',str(exe)],env=env,check=True)
 raw=a.main_model.read_bytes();bad=bytearray(raw);bad[123]^=1
 files={'bad':bad,'short':raw[:-1],'long':raw+b'!','empty':b'','large':b'X'*50000,'empty.small':b'X'*32}
 for name,data in files.items():(out/name).write_bytes(data)
 subprocess.run([str(exe),str(a.main_model.resolve()),str(a.secondary_model.resolve())]+[str(out/n) for n in ['bad','short','long','empty','large']],check=True)
print(json.dumps(dict(passed=True,scope='actual role loader, allocator, file I/O and SHA256; stub interpreter',switches=6,rejected_cases=9,workspace_preserved=True,hardware_switching_verified=False)))
