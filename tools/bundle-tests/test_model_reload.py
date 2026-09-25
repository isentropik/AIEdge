"""Compile actual loader and allocator methods with a tracked interpreter stub.
Run with Python and ziglang installed; no board or SDK required.
"""
import os,sys,tempfile
if os.name == 'nt':
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)
import json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
_workspace=tempfile.TemporaryDirectory(prefix='aiedge-model-reload-')
OUT=Path(_workspace.name)
source=(ROOT/'code/components/jomjol_tfliteclass/CTfLiteClass.cpp').read_text(encoding='utf-8')
def part(a,b):return source[source.index(a):source.index(b,source.index(a))]
methods=part('bool CTfLiteClass::MakeStaticResolver()', 'float CTfLiteClass::GetOutputValue')
methods+=part('bool CTfLiteClass::MakeAllocate()', 'void CTfLiteClass::GetInputTensorSize')
methods+=part('long CTfLiteClass::GetFileSize(', 'bool CTfLiteClass::LoadFrozenPolarModel(')
methods+=source[source.index('CTfLiteClass::CTfLiteClass()'):]
allocator=(ROOT/'code/components/jomjol_helper/psram.cpp').read_text(encoding='utf-8')
allocator=allocator[allocator.index('void *psram_get_shared_tensor_arena_memory(void)'):allocator.index('void *malloc_psram_heap(')]
allocator=allocator.replace('    sharedMemoryInUseFor = "";', '    assert(live==0);++freed;sharedMemoryInUseFor = "";')
harness=r"""
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <string>
#include <sys/stat.h>
const int kTfLiteOk=0,ESP_LOG_DEBUG=0,ESP_LOG_INFO=1,ESP_LOG_ERROR=2;
using TfLiteStatus=int;
const char* TAG="test";const int MAX_MODEL_SIZE=128,TENSOR_ARENA_SIZE=256;
unsigned char region[384];unsigned char* modelMemory=region+256;unsigned char* arena=region;void* shared_region=region;std::string sharedMemoryInUseFor;int live=0,destroyed=0,freed=0,registrations=0,failRegistration=0;bool allocationFails=false;
struct Logger{void WriteToFile(int,const char*,std::string){} void WriteHeapInfo(const char*){}} LogFile;
using std::to_string;
"""+allocator+r"""
struct Resolver {
 int add(){++registrations;return registrations==failRegistration?1:0;}
 int AddFullyConnected(){return add();}int AddReshape(){return add();}int AddSoftmax(){return add();}
 int AddConv2D(){return add();}int AddMaxPool2D(){return add();}int AddQuantize(){return add();}
 int AddMul(){return add();}int AddAdd(){return add();}int AddLeakyRelu(){return add();}int AddDequantize(){return add();}
};
namespace tflite {
struct Model{};
const Model* GetModel(unsigned char* p){return reinterpret_cast<const Model*>(p);}
struct MicroInterpreter {
 const unsigned char* bytes;unsigned char saved;
 MicroInterpreter(const Model* m,Resolver&,uint8_t*,int):bytes(reinterpret_cast<const unsigned char*>(m)),saved(*bytes){assert(live==0);++live;}
 ~MicroInterpreter(){assert(*bytes==saved);--live;++destroyed;}
 int AllocateTensors(){return allocationFails?1:0;}
};}
class CTfLiteClass {
public:
 Resolver resolver;const tflite::Model* model=nullptr;tflite::MicroInterpreter* interpreter=nullptr;
 int kTensorArenaSize;uint8_t* tensor_arena=nullptr;unsigned char* modelfile=nullptr;
 size_t loadedModelBytes=0;bool verifiedPolarModel=false,resolverAttempted=false,resolverReady=false;
 float* input=nullptr;void* output=nullptr;
 CTfLiteClass();~CTfLiteClass();bool MakeStaticResolver();void ResetInterpreter();bool MakeAllocate();
 long GetFileSize(std::string);bool ReadFileToModel(std::string);bool LoadModel(std::string);
};
"""+methods+r"""
int main(int argc,char**argv){
 assert(argc==3);const std::string a=argv[1],b=argv[2];
 {CTfLiteClass net;
  assert(net.LoadModel(a));assert(net.MakeAllocate());assert(live==1&&registrations==10);
  assert(sharedMemoryInUseFor=="Digitization_Model");
  for(int i=64;i<128;++i)modelMemory[i]=0x5a;
  net.input=reinterpret_cast<float*>(arena);net.output=arena;
  assert(net.LoadModel(b));assert(live==0&&destroyed==1&&freed==0);
  assert(!net.input&&!net.output&&modelMemory[0]==0x22);
  for(int i=64;i<128;++i)assert(modelMemory[i]==0x5a);
  assert(net.MakeAllocate());assert(live==1&&registrations==10);
  assert(net.MakeAllocate());assert(live==1&&destroyed==2&&registrations==10);
  assert(!net.LoadModel(a+".missing"));assert(!net.model&&!net.interpreter&&!net.verifiedPolarModel&&net.loadedModelBytes==0);
  assert(live==0&&destroyed==3&&freed==0);
  assert(!net.MakeAllocate());assert(registrations==10);
  assert(net.LoadModel(a));allocationFails=true;assert(!net.MakeAllocate());
  assert(live==0&&!net.interpreter&&destroyed==4);allocationFails=false;
  assert(net.MakeAllocate());assert(live==1&&registrations==10);
 }
 assert(live==0&&freed==1&&destroyed==5);
 {CTfLiteClass net;failRegistration=registrations+3;
  assert(net.LoadModel(a));assert(!net.MakeAllocate());assert(live==0);
  const int count=registrations;assert(!net.MakeAllocate());assert(registrations==count);
 }
 assert(live==0&&freed==2&&sharedMemoryInUseFor.empty());
 // A rejected second owner must neither write nor release the first allocation.
 {CTfLiteClass first;assert(first.LoadModel(a));assert(first.MakeAllocate());
  {CTfLiteClass second;assert(!second.tensor_arena);assert(!second.LoadModel(b));assert(!second.MakeAllocate());}
  assert(live==1&&freed==2&&modelMemory[0]==0x11&&sharedMemoryInUseFor=="Digitization_Model");
 }
 assert(live==0&&freed==3&&sharedMemoryInUseFor.empty());
 // Non-inference stage ownership survives a failed network construction.
 sharedMemoryInUseFor="TakeImage";
 {CTfLiteClass blocked;assert(!blocked.LoadModel(a));}
 assert(freed==3&&sharedMemoryInUseFor=="TakeImage");
 sharedMemoryInUseFor.clear();shared_region=nullptr;
 {CTfLiteClass unavailable;assert(!unavailable.LoadModel(a));}
 assert(freed==3&&sharedMemoryInUseFor.empty());
}
"""
cpp=OUT/'model_reload_lifecycle.cpp';exe=OUT/'model_reload_lifecycle.exe';cpp.write_text(harness,encoding='utf-8')
a=OUT/'lifecycle-model-a.bin';b=OUT/'lifecycle-model-b.bin';a.write_bytes(bytes([0x11])*64);b.write_bytes(bytes([0x22])*64)
env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(OUT/'zig-global-cache'),ZIG_LOCAL_CACHE_DIR=str(OUT/'zig-local-cache'))
subprocess.run([sys.executable,'-m','ziglang','c++','-std=c++11','-O2','-UNDEBUG',str(cpp),'-o',str(exe)],env=env,check=True)
subprocess.run([str(exe),str(a),str(b)],check=True)
report={'passed':True,'scope':'actual loader/shared allocator/allocation/destructor/resolver methods; fake interpreter tracks old model bytes until teardown and one shared allocation release per owner','cases':['reload destroys before overwrite','same resolver not registered twice','repeat allocation destroys old interpreter','missing reload invalidates prior state','allocation failure clears interpreter','retry allocation','one shared release per owner','resolver failure not retried into partial table','real allocator reload uses existing ownership','equal-size reload preserves workspace tail','failed second owner cannot release active memory','capture-stage ownership preserved'],'physical_runtime_tested':False}
(OUT/'model-reload-lifecycle-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
