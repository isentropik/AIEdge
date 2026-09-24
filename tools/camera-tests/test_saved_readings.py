"""Compile actual saved-reading load/save methods against local file fixtures."""
import argparse,os,subprocess,tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--zig-python',required=True);a=p.parse_args();root=Path(__file__).resolve().parents[2]
s=(root/'code/components/jomjol_flowcontroll/ClassFlowPostProcessing.cpp').read_text();start=s.index('bool ClassFlowPostProcessing::LoadPreValue(');end=s.index('ClassFlowPostProcessing::ClassFlowPostProcessing(',start);methods=s[start:end]
pre=r'''
#include <cassert>
#include "SavedReadingTime.h"
#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <cstdio>
#include <ctime>
#include <string>
#include <vector>
#include <sstream>
#include <iostream>
using namespace std;
#define ESP_LOGD(...) ((void)0)
#define PREVALUE_TIME_FORMAT_INPUT "%d-%d-%dT%d:%d:%d"
#define PREVALUE_TIME_FORMAT_OUTPUT "%Y-%m-%dT%H:%M:%S%z"
const int ESP_LOG_ERROR=0;const char* TAG="test";
struct Logger {void WriteToFile(int,const char*,string){}}LogFile;
bool failWrite=false,failClose=false;
int openFiles=0;FILE* trackedOpen(const char*p,const char*m){FILE*f=std::fopen(p,m);if(f)++openFiles;return f;}
int trackedClose(FILE*f){assert(f);--openFiles;int result=std::fclose(f);return failClose?EOF:result;}
int trackedPuts(const char*s,FILE*f){return failWrite?EOF:std::fputs(s,f);}
string trim(string s){auto a=s.find_first_not_of(" \t\r\n");if(a==string::npos)return "";return s.substr(a,s.find_last_not_of(" \t\r\n")-a+1);}
vector<string> HelperZerlegeZeile(string s,string delimiter){vector<string>v;size_t p;while((p=s.find(delimiter))!=string::npos){v.push_back(trim(s.substr(0,p)));s.erase(0,p+delimiter.size());}v.push_back(trim(s));return v;}
string RundeOutput(double v,int){return to_string(v);}
struct Number {string name="main",ReturnPreValue,ReturnValue,timeStamp;double PreValue=0,Value=0;int Nachkomma=0;bool PreValueOkay=false;time_t timeStampLastPreValue=0,timeStampTimeUTC=0;void*digit_roi=nullptr;void*analog_roi=nullptr;};
struct ClassFlowPostProcessing {bool UpdatePreValueINI=false;int PreValueAgeStartup=30;string FilePreValue;vector<Number*>NUMBERS;bool LoadPreValue();void SavePreValue();};
#define fopen trackedOpen
#define fclose trackedClose
#define fputs trackedPuts
'''
post=r'''
#undef fopen
#undef fclose
#undef fputs
int main(int argc,char**argv){assert(argc==2);string path=argv[1];Number n;ClassFlowPostProcessing p;p.NUMBERS={&n};p.FilePreValue=path;
 auto load=[&](string data){FILE*f=std::fopen(path.c_str(),"wb");assert(f);fwrite(data.data(),1,data.size(),f);std::fclose(f);n.PreValueOkay=false;bool result=p.LoadPreValue();assert(openFiles==0);return result;};
 time_t parsed=0;
 assert(SavedReadingTime::parse("2024-02-29T00:00:00Z",parsed)&&parsed==1709164800);
 for(string stamp:{"2024-02-29T00:00:00+0000","2024-02-28T17:00:00-0700","2024-02-29T05:30:00+0530"})assert(SavedReadingTime::parse(stamp,parsed)&&parsed==1709164800);
 assert(SavedReadingTime::parse("2000-02-29T12:00:00Z",parsed));
 for(string stamp:{"2100-02-29T00:00:00Z","2026-00-01T00:00:00Z","2026-13-01T00:00:00Z","2026-01-00T00:00:00Z","2026-04-31T00:00:00Z","2026-01-01T24:00:00Z","2026-01-01T00:60:00Z","2026-01-01T00:00:60Z","2026-01-01T00:00:00+2400","2026-01-01T00:00:00+0060","2026-01-01T00:00:00junk","2026-1-01T00:00:00Z","2026-01-01T00:00:00z"})assert(!SavedReadingTime::parse(stamp,parsed));
 time_t now=time(nullptr);char b[80];strftime(b,sizeof(b),PREVALUE_TIME_FORMAT_OUTPUT,localtime(&now));string stamp=b;
 assert(load("main\t"+stamp+"\t255440\n"));assert(n.PreValue==255440&&n.PreValueOkay);
 for(string data:{string(""),string("\n"),string("main\t")+stamp+"\n",string("main\t")+stamp+"\t1\nsecondary\t"+stamp+"\n",stamp+"\n",string("main\t")+stamp+"\tbad\n",string("main\t")+stamp+"\tnan\n",string("main\t")+stamp+"\tinf\n",string("main\t")+stamp+"\t1e999\n",string("main\tinvalid\t1\n"),stamp+"\ninvalid\n"})assert(!load(data));
 // Reject impossible calendar dates rather than letting mktime normalize them.
 assert(!load("main\t2026-02-30T12:00:00+0000\t1\n"));
 time_t future=now+3600;strftime(b,sizeof(b),PREVALUE_TIME_FORMAT_OUTPUT,localtime(&future));
 assert(load("main\t"+string(b)+"\t1\n"));assert(!n.PreValueOkay);
 assert(!load(string(b)+"\n1\n"));
 // Failure after a valid first row must preserve every runtime value.
 Number secondary;secondary.name="secondary";p.NUMBERS={&n,&secondary};
 n.PreValue=42;n.Value=43;n.PreValueOkay=true;n.ReturnPreValue="42";n.ReturnValue="43";n.timeStampLastPreValue=123;p.UpdatePreValueINI=true;
 {FILE*f=std::fopen(path.c_str(),"wb");string data="main\t"+stamp+"\t255440\nsecondary\t"+stamp+"\tbroken\n";fwrite(data.data(),1,data.size(),f);std::fclose(f);}
 assert(!p.LoadPreValue());assert(openFiles==0);assert(n.PreValue==42&&n.Value==43&&n.PreValueOkay&&n.ReturnPreValue=="42"&&n.ReturnValue=="43"&&n.timeStampLastPreValue==123&&p.UpdatePreValueINI);
 p.NUMBERS={&n};
 assert(load(stamp+"\n255440\n"));assert(n.PreValue==255440);
 for(int failure=0;failure<2;++failure){p.FilePreValue=path;p.UpdatePreValueINI=true;failWrite=failure==0;failClose=failure==1;p.SavePreValue();assert(p.UpdatePreValueINI&&openFiles==0);failWrite=failClose=false;}
 p.UpdatePreValueINI=true;p.SavePreValue();assert(!p.UpdatePreValueINI&&openFiles==0);
 p.FilePreValue=path+"/missing/prevalue.ini";p.UpdatePreValueINI=true;p.SavePreValue();assert(p.UpdatePreValueINI&&openFiles==0);
 cout<<"Saved readings: current/legacy valid formats, empty and truncated files, invalid numbers/timestamps, handle closure and failed-open retry passed.\n";
}
'''
with tempfile.TemporaryDirectory(prefix='aiedge-prevalue-') as d:
 d=Path(d);cpp=d/'test.cpp';cpp.write_text(pre+methods+post,encoding='utf-8');exe=d/('test.exe' if os.name=='nt' else 'test')
 subprocess.run([a.zig_python,'-m','ziglang','c++','-std=c++17','-O0','-I'+str(root/'code/components/jomjol_flowcontroll'),str(cpp),'-o',str(exe)],check=True);subprocess.run([str(exe),str(d/'prevalue.ini')],check=True)
