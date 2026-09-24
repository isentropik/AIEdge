"""Exercise actual normal recognition control flow with explicit dependency faults.
Model mathematics and ESP32 memory capacity are outside this host test's scope.
"""
import argparse, os, subprocess, tempfile
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--zig-python');p.add_argument('--cxx',default='c++');a=p.parse_args()
root=Path(__file__).resolve().parents[2]
source=(root/'code/components/jomjol_flowcontroll/ClassFlowCNNPolar.cpp').read_text(encoding='utf-8')
source='\n'.join(s for s in source.splitlines() if not s.startswith('#include'))
harness=r'''
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <new>
#include <string>
#include <vector>
#include "PolarCalibration.h"
using std::string;
constexpr int ESP_LOG_ERROR=1,ESP_LOG_DEBUG=2;
int rejected=0,observed=0,prepared=0,inferred=0,previewed=0,cleaned=0;
int failPrepare=-1,failInfer=-1;
bool modelOk=true,allocateOk=true,contractOk=true,workspaceOk=true,alignOk=true;
struct Image {
 int width=640,height=480,channels=3;
 unsigned char bytes[150*150*3]={};unsigned char* rgb_image=bytes;
 int64_t captureMonotonicUs=123456;bool captureTimestampValid=true;
 void Resize(int,int,Image*){++previewed;}
};
using CAlignAndCutImage=Image;
struct ROI {string name;int posx,posy,deltax,deltay;bool CCW,isReject=false;float result_float=8;Image* image_org;Image* image;};
struct Group {string name;std::vector<ROI*> ROI;};
std::vector<Group*>* groups=nullptr;
void assertUnpublished(){for(auto*g:*groups)for(auto*r:g->ROI)assert(r->isReject&&std::isnan(r->result_float));}
namespace polar {
struct PipelineScratch {signed char features[384*40];unsigned char crop[150*150*3];int visibilityScore;};
enum class AlignmentStatus {Ok,Bad};
AlignmentStatus alignFrame(unsigned char*,int,int,PipelineScratch&,double*){assertUnpublished();return alignOk?AlignmentStatus::Ok:AlignmentStatus::Bad;}
bool prepareDial(unsigned char*,double*,int i,PipelineScratch&,void*,void*,bool sparse){assert(sparse);assertUnpublished();++prepared;return i!=failPrepare;}
}
struct CTfLiteClass {
 alignas(8) unsigned char storage[sizeof(polar::PipelineScratch)];
 bool LoadFrozenPolarModel(string){assertUnpublished();return modelOk;}
 bool MakeAllocate(){return allocateOk;}
 bool HasPolarTensorContract(){return contractOk;}
 void* GetPolarWorkspace(size_t size){assert(size==sizeof(polar::PipelineScratch));return workspaceOk?storage:nullptr;}
 bool InferPolar(signed char*,int n,bool ccw,float& value){assert(n==384*40);assertUnpublished();int i=inferred++;assert(ccw==polar::dials[i].ccw);value=float(i)+.25f;return i!=failInfer;}
};
struct Alignment {bool geometry=true;Image* image=nullptr;bool HasFrozenPolarAlignment(){return geometry;}Image* GetAlignAndCutImage(){return image;}};
namespace MeterBundle {string frozenModelPath(string x){return x;}}
string FormatFileName(string x){return x;}
namespace meter {const char* sessionStateName(int){return "ok";}const char* intervalStatusName(int){return "ok";}}
namespace PolarAccounting {
 void reject(){++rejected;assertUnpublished();}
 void observe(float* values,int64_t timestamp,bool valid){assertUnpublished();assert(timestamp==123456&&valid);for(int i=0;i<6;++i)assert(values[i]==float(i)+.25f);++observed;}
 struct Snapshot {int state;struct {int status;}interval;};Snapshot snapshot(){return {};}
}
struct Logger {void WriteToFile(int,const char*,string){}}LogFile;
int64_t esp_timer_get_time(){static int64_t t=0;return ++t;}
void esp_task_wdt_reset(){}void vTaskDelay(int){}
struct ClassFlowCNNGeneral {
 Alignment* flowpostalignment=nullptr;std::vector<Group*> GENERAL;
 string cnnmodelfile="/config/polar-int8.tflite";int modelxsize=10,modelysize=10;
 bool validatePolarGeometry();bool doPolarNetwork(string);
 void RemoveOldLogs(){++cleaned;}
};
'''+source+r'''
struct Fixture {
 Image input,original[6],preview[6];ROI rows[6];Group main,secondary;Alignment alignment;ClassFlowCNNGeneral flow;
 Fixture(){
 rejected=observed=prepared=inferred=previewed=cleaned=0;failPrepare=failInfer=-1;
 modelOk=allocateOk=contractOk=workspaceOk=alignOk=true;
 main.name="main";secondary.name="secondary";
 for(int i=0;i<6;++i){auto&d=polar::dials[i];string n=d.name;rows[i]={n.substr(n.find('_')+1),d.x,d.y,d.w,d.h,d.ccw,false,8,&original[i],&preview[i]};(i<5?main:secondary).ROI.push_back(&rows[i]);}
 alignment.image=&input;flow.flowpostalignment=&alignment;flow.GENERAL={&main,&secondary};groups=&flow.GENERAL;
 }
 void fails(){assert(!flow.doPolarNetwork("fixture"));assert(rejected==1&&observed==0&&cleaned==0);assertUnpublished();}
 void passes(){assert(flow.doPolarNetwork("fixture"));assert(rejected==0&&observed==1&&prepared==6&&inferred==6&&previewed==6&&cleaned==1);for(int i=0;i<6;++i)assert(!rows[i].isReject&&rows[i].result_float==float(i)+.25f);}
};
int main(){
 {Fixture f;f.passes();}
 for(int fault=0;fault<4;++fault){Fixture f;bool* targets[]={&modelOk,&allocateOk,&contractOk,&workspaceOk};*targets[fault]=false;f.fails();}
 {Fixture f;alignOk=false;f.fails();}
 for(int i=0;i<6;++i){Fixture f;failPrepare=i;f.fails();assert(inferred==i);}
 for(int i=0;i<6;++i){Fixture f;failInfer=i;f.fails();assert(inferred==i+1);}
 for(int i=0;i<6;++i)for(int kind=0;kind<4;++kind){Fixture f;if(kind==0)f.rows[i].image_org=nullptr;if(kind==1)f.original[i].rgb_image=nullptr;if(kind==2)f.rows[i].image=nullptr;if(kind==3)f.preview[i].rgb_image=nullptr;f.fails();}
 {Fixture f;f.flow.flowpostalignment=nullptr;f.fails();}
 {Fixture f;f.alignment.geometry=false;f.fails();}
 for(int kind=0;kind<5;++kind){Fixture f;if(kind==0)f.alignment.image=nullptr;if(kind==1)f.input.width=1;if(kind==2)f.input.height=1;if(kind==3)f.input.channels=1;if(kind==4)f.input.rgb_image=nullptr;f.fails();}
 for(int i=0;i<6;++i)for(int kind=0;kind<6;++kind){Fixture f;auto&r=f.rows[i];if(kind==0)r.name="wrong";if(kind==1)++r.posx;if(kind==2)++r.posy;if(kind==3)++r.deltax;if(kind==4)++r.deltay;if(kind==5)r.CCW=!r.CCW;f.fails();}
 {Fixture f;f.main.ROI.erase(f.main.ROI.begin());f.fails();}
 {Fixture f;f.secondary.ROI.push_back(&f.rows[5]);f.fails();}
 {Fixture f;std::swap(f.main.ROI[0],f.main.ROI[1]);f.fails();}
 // Previously successful values must all be invalidated on the next failed frame.
 {Fixture f;f.passes();observed=rejected=prepared=inferred=previewed=cleaned=0;failInfer=5;f.fails();}
}
'''
with tempfile.TemporaryDirectory(prefix='aiedge-normal-') as d:
 d=Path(d);cpp=d/'test.cpp';exe=d/('test.exe' if os.name=='nt' else 'test')
 cpp.write_text(harness,encoding='utf-8')
 compiler=[a.zig_python,'-m','ziglang','c++'] if a.zig_python else [a.cxx]
 subprocess.run(compiler+['-std=c++17','-O0','-I',str(root/'code/components/jomjol_tfliteclass'),str(cpp),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
print('Normal recognition: success, stage faults, 6-dial geometry, stale-output invalidation and accounting isolation passed.')
