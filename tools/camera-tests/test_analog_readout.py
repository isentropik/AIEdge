"""Actual analog readout/carry and decimal-shift routines; no devices or images."""
import argparse,os,re,subprocess,tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--zig-python');p.add_argument('--cxx',default='c++');a=p.parse_args()
root=Path(__file__).resolve().parents[2];flow=root/'code/components/jomjol_flowcontroll'
s=(flow/'ClassFlowCNNGeneral.cpp').read_text(encoding='utf-8')
start=s.index('string ClassFlowCNNGeneral::getReadout(');end=s.index('    if (CNNType == Digit)',start)
readout=s[start:end].replace('int _analog = 0','int _analog')+'return "unsupported"; }\n'
start=s.index('int ClassFlowCNNGeneral::PointerEvalAnalogNew(');end=s.index('bool ClassFlowCNNGeneral::ReadParameter',start);pointer=s[start:end]
s=(flow/'ClassFlowPostProcessing.cpp').read_text(encoding='utf-8');start=s.index('string ClassFlowPostProcessing::ShiftDecimal(');end=s.index('bool ClassFlowPostProcessing::doFlow',start);shift=s[start:end]
defines=(root/'code/include/defines.h').read_text(encoding='utf-8');error=int(re.search(r'#define Analog_error (\d+)',defines)[1])
harness=r'''
#include <cassert>
#include <cmath>
#include <iostream>
#include <limits>
#include <string>
#include <vector>
using std::string;
const int Analogue=1,Analogue100=2,ESP_LOG_DEBUG=0;
const char* TAG="test";
struct Logger {void WriteToFile(int,const char*,string){}} LogFile;
struct Item {float result_float;bool isReject=false;};
struct Group {std::vector<Item*> ROI;};
struct ClassFlowCNNGeneral {int CNNType=Analogue;bool usePolarReader=true,disabled=false;std::vector<Group*> GENERAL;int PointerEvalAnalogNew(float,int);string getReadout(int,bool,int=-1,float=0,float=0);};
struct ClassFlowPostProcessing {string ShiftDecimal(string,int);};
int findDelimiterPos(string s,string delimiter){return static_cast<int>(s.find(delimiter));}
'''+f'constexpr int Analog_error={error};\n'+readout+pointer+shift+r'''
string converted(std::vector<float> values,bool extended,int initialShift) {
 std::vector<Item> items;for(float v:values)items.push_back({v,false});Group group;for(auto&v:items)group.ROI.push_back(&v);
 ClassFlowCNNGeneral reader;reader.GENERAL={&group};ClassFlowPostProcessing post;
 return post.ShiftDecimal(reader.getReadout(0,extended),initialShift-(extended?1:0));
}
int main(){
 // Saved-image firmware estimates: 0 at the highest dial stays visible.
 assert(converted({.284501761f,2.51280379f,5.60850716f,5.31036758f,4.42943239f},true,2)=="0255440");
 assert(converted({.28f,2.51f,5.61f,5.3f,4.5f},true,2)=="0255450");
 // Truncate tenths; 8.62 must not be rounded into the next numbered step.
 assert(converted({8.62f},true,0)=="8.6");
 assert(converted({0.f,2.f,5.f,5.f,4.f},false,2)=="0255400");
 assert(converted({0.f,0.f,0.f,0.f,0.f},true,2)=="0000000");
 // Carry resolution uses the following dial; individual positions can wrap.
 assert(converted({9.98f,.02f},false,0)=="00");
 assert(converted({.02f,9.98f},false,0)=="99");
 assert(converted({9.98f},true,0)=="9.9");
 assert(converted({.02f},true,0)=="0.0");
 // Legacy secondary readout remains a 0-10 wheel position, not cubic feet.
 assert(converted({4.6440568f},true,0)=="4.6");
 for(int index=0;index<5;++index)for(int fault=0;fault<5;++fault){
  Item values[5]={{0},{2},{5},{5},{4}};Group group;for(auto&v:values)group.ROI.push_back(&v);
  if(fault==0)values[index].isReject=true;
  if(fault==1)values[index].result_float=std::numeric_limits<float>::quiet_NaN();
  if(fault==2)values[index].result_float=std::numeric_limits<float>::infinity();
  if(fault==3)values[index].result_float=-.1;
  if(fault==4)values[index].result_float=10;
  ClassFlowCNNGeneral reader;reader.GENERAL={&group};assert(reader.getReadout(0,true)=="NNNNNN");
 }
 std::cout<<"Analog readout: leading zero, tenths truncation, following-dial carries, decimal scale and invalid-frame rejection passed.\n";
}
'''
with tempfile.TemporaryDirectory(prefix='aiedge-readout-') as d:
 d=Path(d);cpp=d/'test.cpp';exe=d/('test.exe' if os.name=='nt' else 'test');cpp.write_text(harness,encoding='utf-8')
 compiler=[a.zig_python,'-m','ziglang','c++'] if a.zig_python else [a.cxx]
 subprocess.run(compiler+['-std=c++17','-O0',str(cpp),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
