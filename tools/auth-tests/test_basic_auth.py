"""Exercise the actual authentication filter with deterministic HTTP/crypto adapters."""
import json, os, subprocess, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
if os.name == 'nt':
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)
OUT=Path(tempfile.mkdtemp(prefix='aiedge-auth-test-'))
source=(ROOT/'code/components/jomjol_wlan/basic_auth.cpp').read_text(encoding='utf-8-sig')
source='\n'.join(line for line in source.splitlines() if not line.startswith('#include'))
cpp=OUT/'basic_auth_test.cpp'
cpp.write_text(r'''
#include <cassert>
#include <string>
#include <vector>
#include <cstring>
#include <algorithm>
using esp_err_t=int;constexpr int ESP_OK=0;
#define ESP_LOGE(...) ((void)0)
struct {std::string http_username,http_password;} wlan_config;
struct httpd_req_t {std::string authorization,status,body,realm,cache;bool readFail=false;int calls=0;};
size_t httpd_req_get_hdr_value_len(httpd_req_t*r,const char*){return r->authorization.size();}
int httpd_req_get_hdr_value_str(httpd_req_t*r,const char*,char*b,size_t n){if(r->readFail||n<=r->authorization.size())return -1;memcpy(b,r->authorization.data(),r->authorization.size());b[r->authorization.size()]=0;return 0;}
int httpd_resp_set_status(httpd_req_t*r,const char*v){r->status=v;return 0;}
int httpd_resp_set_type(httpd_req_t*,const char*){return 0;}
int httpd_resp_set_hdr(httpd_req_t*r,const char*k,const char*v){if(std::string(k)=="WWW-Authenticate")r->realm=v;if(std::string(k)=="Cache-Control")r->cache=v;return 0;}
int httpd_resp_send(httpd_req_t*r,const char*b,size_t n){r->body.assign(b,n);return 0;}
bool encodeFail=false;
int esp_crypto_base64_encode(unsigned char*out,size_t capacity,size_t*written,const unsigned char*data,size_t size){
 const char*alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";std::string result;
 for(size_t i=0;i<size;i+=3){unsigned n=unsigned(data[i])<<16;if(i+1<size)n|=unsigned(data[i+1])<<8;if(i+2<size)n|=data[i+2];result+=alphabet[(n>>18)&63];result+=alphabet[(n>>12)&63];result+=(i+1<size?alphabet[(n>>6)&63]:'=');result+=(i+2<size?alphabet[n&63]:'=');}
 if(!out||capacity<result.size()+1){*written=result.size()+1;return -1;}if(encodeFail)return -1;
 memcpy(out,result.c_str(),result.size()+1);*written=result.size();return 0;
}
int target(httpd_req_t*r){++r->calls;return 17;}
'''+source+r'''
int main(){
 httpd_req_t r;init_basic_auth();assert(!basic_auth_configured());assert(basic_auth_request_filter(&r,target)==17&&r.calls==1);
 wlan_config.http_username="admin";wlan_config.http_password="test-password";init_basic_auth();assert(basic_auth_configured());
 const std::string correct="Basic YWRtaW46dGVzdC1wYXNzd29yZA==";
 auto reject=[&](const std::string&value,bool readFail=false){r={};r.authorization=value;r.readFail=readFail;assert(basic_auth_request_filter(&r,target)==0);assert(!r.calls&&r.status=="401 Unauthorized"&&r.cache=="no-store"&&r.realm.find("AIEdge")!=std::string::npos);};
 for(size_t n=0;n<correct.size();++n)reject(correct.substr(0,n));
 reject(correct+"x");reject(std::string(10000,'a'));reject(correct,true);
 for(size_t n=0;n<correct.size();++n){auto value=correct;value[n]='\0';reject(value);value=correct;value[n]^=1;reject(value);}
 r={};r.authorization=correct;assert(basic_auth_request_filter(&r,target)==17&&r.calls==1);
 wlan_config.http_password=std::string(10000,'z');r={};r.authorization=correct;assert(basic_auth_request_filter(&r,target)==17); // owned active snapshot
 wlan_config.http_password="";init_basic_auth();assert(!basic_auth_configured());reject(correct);
 wlan_config.http_username="";wlan_config.http_password="x";init_basic_auth();reject(correct);
 wlan_config.http_username="a:b";init_basic_auth();reject(correct);
 wlan_config.http_username="admin";wlan_config.http_password="test-password";encodeFail=true;init_basic_auth();reject(correct);encodeFail=false;
 init_basic_auth();assert(basic_auth_configured());wlan_config.http_username="";wlan_config.http_password="";init_basic_auth();assert(!basic_auth_configured());r={};assert(basic_auth_request_filter(&r,target)==17);
}
''',encoding='utf-8')
exe=cpp.with_suffix('.exe')
env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(OUT/'zig-global-cache'),ZIG_LOCAL_CACHE_DIR=str(OUT/'zig-local-cache'))
subprocess.run([sys.executable,'-m','ziglang','c++','-std=c++11','-O2','-UNDEBUG',str(cpp),'-o',str(exe)],check=True,env=env)
subprocess.run([str(exe)],check=True)
result={'passed':True,'actual_filter_source':True,'http_and_base64_adapters':True,'hardware_verified':False,'coverage':['missing/wrong/truncated/oversized headers','every embedded NUL and single-byte mutation','header read failure','exact valid credential','owned credential snapshot','partial configuration fails closed','encoder failure fails closed','reinitialization clears old credentials']}
(OUT/'results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
