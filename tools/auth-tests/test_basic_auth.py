"""Actual website HTTP adapter with deterministic HTTP, clock and base64 substitutes."""
import os,sys,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(tempfile.mkdtemp(prefix='aiedge-http-auth-'));STUB=OUT/'stubs';(STUB/'mbedtls').mkdir(parents=True)
if os.name=='nt':
 import ctypes
 ctypes.windll.kernel32.SetErrorMode(3)
(STUB/'esp_http_server.h').write_text(r'''#pragma once
#include <string>
#include <map>
#include <cstring>
#include <algorithm>
using esp_err_t=int;constexpr int ESP_OK=0,HTTP_GET=0,HTTP_POST=1;
struct httpd_req_t{const char*uri="/";int method=HTTP_GET,content_len=0,calls=0;size_t offset=0;bool headerFail=false,readFail=false;std::string body,response,status="200 OK",type;std::map<std::string,std::string> headers,out;};
inline size_t httpd_req_get_hdr_value_len(httpd_req_t*r,const char*k){return r->headers[k].size();}
inline int httpd_req_get_hdr_value_str(httpd_req_t*r,const char*k,char*b,size_t n){auto&v=r->headers[k];if(r->headerFail||v.size()>=n)return -1;memcpy(b,v.data(),v.size());b[v.size()]=0;return 0;}
inline int httpd_req_recv(httpd_req_t*r,char*b,size_t n){if(r->readFail)return -1;size_t got=std::min({n,size_t(3),r->body.size()-r->offset});memcpy(b,r->body.data()+r->offset,got);r->offset+=got;return got;}
inline int httpd_resp_set_status(httpd_req_t*r,const char*v){r->status=v;return 0;}
inline int httpd_resp_set_type(httpd_req_t*r,const char*v){r->type=v;return 0;}
inline int httpd_resp_set_hdr(httpd_req_t*r,const char*k,const char*v){r->out[k]=v;return 0;}
inline int httpd_resp_send(httpd_req_t*r,const char*b,size_t n){r->response.assign(b,n);return 0;}
''')
(STUB/'esp_timer.h').write_text('#pragma once\n#include <cstdint>\nextern uint64_t now;inline uint64_t esp_timer_get_time(){return now;}\n')
(STUB/'mbedtls/base64.h').write_text(r'''#pragma once
#include <string>
inline int mbedtls_base64_decode(unsigned char*out,size_t cap,size_t*count,const unsigned char*in,size_t n){
 const std::string alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";unsigned value=0,bits=0;*count=0;
 for(size_t i=0;i<n;++i){if(in[i]=='=')break;auto digit=alphabet.find(char(in[i]));if(digit==std::string::npos)return -1;value=(value<<6)|digit;bits+=6;if(bits>=8){bits-=8;if(*count>=cap)return -1;out[(*count)++]=(value>>bits)&255;}}return 0;
}
''')
cpp=OUT/'http.cpp';cpp.write_text(r'''
#include "credential_test_backend.h"
#include "WebsiteHttp.h"
#include <string>
uint64_t now=0;
int target(httpd_req_t*r){++r->calls;return 777;}
std::string encode(const std::string&s){const char*a="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";std::string out="Basic ";for(size_t i=0;i<s.size();i+=3){unsigned n=unsigned(uint8_t(s[i]))<<16;if(i+1<s.size())n|=unsigned(uint8_t(s[i+1]))<<8;if(i+2<s.size())n|=uint8_t(s[i+2]);out+=a[(n>>18)&63];out+=a[(n>>12)&63];out+=i+1<s.size()?a[(n>>6)&63]:'=';out+=i+2<s.size()?a[n&63]:'=';}return out;}
int main(){Fake f;WebsiteAccess state(f);WebsiteHttp http(state);httpd_req_t r;
 http.handle(&r,target);assert(r.status=="503 Service Unavailable"&&!r.calls);http.initialize();
 r={};http.handle(&r,target);assert(r.status=="200 OK"&&r.response.find("Create a website password")!=std::string::npos&&!r.calls);
 r={};r.uri="/?installed=123";http.handle(&r,target);assert(r.status=="200 OK"&&r.response.find("Create a website password")!=std::string::npos&&!r.calls);
 for(auto path:{"/sysinfo","/img_tmp/alg.jpg","/fileserver/config/config.ini","/stream","/bundle_install","/status","/debug-log","/networks","/auth/setup?x"}){r={};r.uri=path;http.handle(&r,target);assert(r.status=="423 Locked"&&!r.calls);}
 std::string token;char hex[3];for(unsigned i=1;i<=32;++i){snprintf(hex,sizeof hex,"%02x",i);token+=hex;}
 auto setup=[&](const std::string&t,const std::string&p,bool readFail=false){r={};r.uri="/auth/setup";r.method=HTTP_POST;r.headers["X-AIEdge-Setup"]=t;r.body=p;r.content_len=p.size();r.readFail=readFail;http.handle(&r,target);};
 const std::string pass(reinterpret_cast<const char*>(password));setup("",pass);assert(r.status=="400 Bad Request"&&f.writes==0);setup(std::string(64,'g'),pass);assert(r.status=="400 Bad Request"&&f.writes==0);setup(token,"short");assert(r.status=="400 Bad Request"&&f.writes==0);setup(token,pass,true);assert(r.status=="400 Bad Request"&&f.writes==0);setup(token,pass);assert(r.status=="200 OK"&&http.configured()&&f.writes==1);setup(token,pass);assert(r.status=="409 Conflict"&&f.writes==1);
 const auto correct=encode("admin:"+pass);
 for(auto path:{"/","/sysinfo","/img_tmp/alg.jpg","/fileserver/config/config.ini","/stream","/bundle_install","/status","/debug-log","/networks"}){r={};r.uri=path;http.handle(&r,target);assert(r.status=="401 Unauthorized"&&!r.calls&&r.out["WWW-Authenticate"].find("AIEdge")!=std::string::npos);r={};r.uri=path;r.headers["Authorization"]=correct;assert(http.handle(&r,target)==777&&r.calls==1);}
 r={};r.headers["Authorization"]=correct;r.headerFail=true;http.handle(&r,target);assert(r.status=="401 Unauthorized"&&!r.calls);
 for(auto bad:{encode("other:"+pass),std::string(300,'a'),std::string("Basic !")}){r={};r.headers["Authorization"]=bad;http.handle(&r,target);assert(r.status=="401 Unauthorized"&&!r.calls);}
 r={};r.headers["Authorization"]=encode("admin:wrong");http.handle(&r,target);assert(r.status=="401 Unauthorized");r={};r.headers["Authorization"]=encode("admin:anotherwrong");http.handle(&r,target);assert(r.status=="429 Too Many Requests");r={};r.headers["Authorization"]=correct;assert(http.handle(&r,target)==777);
 r={};r.uri="/auth/password";r.headers["Authorization"]=correct;http.handle(&r,target);assert(r.status=="200 OK"&&r.response.find("Change website password")!=std::string::npos&&!r.calls);
 auto change=[&](const std::string& authorization,const std::string& action,const std::string& next,bool readFail=false){r={};r.uri="/auth/password";r.method=HTTP_POST;r.headers["Authorization"]=authorization;r.headers["X-AIEdge-Password-Change"]=action;r.body=next;r.content_len=next.size();r.readFail=readFail;http.handle(&r,target);};
 const std::string next="another-new-password";const auto nextAuth=encode("admin:"+next);
 change(correct,"",next);assert(r.status=="400 Bad Request"&&f.writes==1);
 change(correct,"confirm",next,true);assert(r.status=="400 Bad Request"&&f.writes==1);
 change(correct,"confirm","short");assert(r.status=="400 Bad Request"&&f.writes==1);
 change(correct,"confirm",next);assert(r.status=="200 OK"&&f.writes==2);
 now=2000000;r={};r.headers["Authorization"]=correct;http.handle(&r,target);assert(r.status=="401 Unauthorized"&&!r.calls);
 now=3000000;r={};r.headers["Authorization"]=nextAuth;assert(http.handle(&r,target)==777);
 change("","confirm",pass);assert(r.status=="401 Unauthorized"&&f.writes==2);
 f.writeError=true;change(nextAuth,"confirm",pass);assert(r.status=="503 Service Unavailable");r={};r.headers["Authorization"]=nextAuth;http.handle(&r,target);assert(r.status=="503 Service Unavailable"&&!r.calls);f.writeError=false;http.initialize();r={};r.headers["Authorization"]=nextAuth;assert(http.handle(&r,target)==777);
 f.readError=true;http.initialize();r={};r.headers["Authorization"]=correct;http.handle(&r,target);assert(r.status=="503 Service Unavailable"&&!r.calls);
 Fake noRandom;noRandom.randomError=true;WebsiteAccess a(noRandom);WebsiteHttp h(a);h.initialize();r={};h.handle(&r,target);assert(r.status=="503 Service Unavailable");
}
''')
serial=(ROOT/'shared/WebsiteSerial.h').read_text(encoding='utf-8-sig')
queue=serial[serial.index('inline bool queueLocalCommand'):serial.index('inline bool startWebsiteSerial')]
compiled=cpp.read_text()
mocks=r'''
#include <new>
using httpd_handle_t=void*;void(*pendingWork)(void*)=nullptr;void* pendingArgument=nullptr;bool queueFails=false;
int httpd_queue_work(httpd_handle_t,void(*work)(void*),void* argument){if(queueFails)return -1;assert(!pendingWork);pendingWork=work;pendingArgument=argument;return 0;}
void runQueued(){assert(pendingWork);auto work=pendingWork;auto argument=pendingArgument;pendingWork=nullptr;pendingArgument=nullptr;work(argument);}
'''
compiled=compiled.replace('int main(){',mocks+queue+'\nint main(){')
i=compiled.rfind('}')
compiled=compiled[:i]+r'''
 Fake queued;WebsiteAccess qs(queued);WebsiteHttp qh(qs);uint8_t qt[32]={};qs.initialize(qt);assert(qs.setup(qt,32,password,sizeof(password)-1));
 auto server=reinterpret_cast<void*>(1);
 assert(queueLocalCommand(server,qh,"AIEdge AUTH RESET"));assert(queued.erases==0);runQueued();assert(queued.erases==0);
 std::string confirmation="AIEdge AUTH CONFIRM ";char pair[3];for(unsigned n=49;n<=64;++n){snprintf(pair,sizeof pair,"%02x",n);confirmation+=pair;}
 assert(queueLocalCommand(server,qh,confirmation.c_str()));assert(queued.erases==0&&qs.state()==State::Ready);runQueued();assert(queued.erases==1&&qs.state()==State::NeedsSetup);
 queueFails=true;assert(!queueLocalCommand(server,qh,"AIEdge AUTH RESET"));assert(!pendingWork&&queued.erases==1);queueFails=false;
 assert(!queueLocalCommand(nullptr,qh,"AIEdge AUTH RESET"));assert(!queueLocalCommand(server,qh,std::string(100,'x').c_str()));
'''+compiled[i:]
cpp.write_text(compiled)
env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(OUT/'global'),ZIG_LOCAL_CACHE_DIR=str(OUT/'local'));exe=OUT/'http.exe'
subprocess.run([sys.executable,'-m','ziglang','c++','-std=c++11','-O2','-UNDEBUG','-I'+str(STUB),'-I'+str(ROOT/'shared'),'-I'+str(ROOT/'tools/auth-tests'),str(cpp),'-o',str(exe)],check=True,env=env)
subprocess.run([str(exe)],check=True)
print('PASS: actual HTTP gate setup/read/write/access failure paths with HTTP/base64/clock/backend substitutes; no hardware claim')
