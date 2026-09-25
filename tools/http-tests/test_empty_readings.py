"""Compile the actual all-readings response branch with a fake HTTP transport."""
import argparse
from pathlib import Path
import subprocess
import tempfile
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--zig-python');p.add_argument('--cxx',default='c++');a=p.parse_args()
repo=Path(__file__).resolve().parents[2]
s=(repo/'code/components/jomjol_flowcontroll/MainFlowControl.cpp').read_text(encoding='utf-8')
s=s[s.index('esp_err_t handler_wasserzaehler('):]
branch=s[s.index('        if (_all)'):s.index('        std::string *status')]
cpp=r"""
#include <string>
#include <iostream>
using esp_err_t=int;
constexpr int ESP_OK=0, READOUT_TYPE_VALUE=0, READOUT_TYPE_PREVALUE=1, READOUT_TYPE_RAWVALUE=2, READOUT_TYPE_ERROR=3;
#define ESP_LOGD(...) ((void)0)
struct httpd_req_t{};
int sends=0,sendResult=0,lastType=-1;std::string payload,body,mime;
int httpd_resp_set_type(httpd_req_t*,const char* type){mime=type;return 0;}
int httpd_resp_send(httpd_req_t*,const char* data,size_t size){++sends;body.assign(data,size);return sendResult;}
struct Flow {std::string getReadoutAll(int type){lastType=type;return payload;}}flowctrl;
int handle(httpd_req_t* req,std::string _type){bool _all=true;std::string zw;
"""+branch+r"""
return -99;}
int main(){httpd_req_t req;const char* types[]={"value","prevalue","raw","error"};
for(int t=0;t<4;++t)for(int empty=1;empty>=0;--empty)for(int failure=0;failure<2;++failure){
 sends=0;body="unchanged";mime.clear();payload=empty?"":"Main\t0255310\r\nSecondary\t0";sendResult=failure?-42:0;
 int result=handle(&req,types[t]);
 if(sends!=1||body!=payload||mime!="text/plain"||lastType!=t||result!=sendResult){std::cerr<<"Failed type="<<types[t]<<" empty="<<empty<<" transport_failure="<<failure<<" sends="<<sends<<" result="<<result<<"\n";return 1;}
}
std::cout<<"All 16 empty/nonempty reading and transport-result cases passed.\n";}
"""
with tempfile.TemporaryDirectory(prefix='aiedge-readings-') as d:
 out=Path(d);src=out/'test.cpp';exe=out/'test.exe';src.write_text(cpp,encoding='utf-8')
 compiler=[a.zig_python,'-m','ziglang','c++'] if a.zig_python else [a.cxx]
 subprocess.run(compiler+['-std=c++11','-O2',str(src),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True,timeout=10)
