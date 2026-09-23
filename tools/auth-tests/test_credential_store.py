"""Compile credential-state and ESP NVS-adapter fault tests (host substitutes)."""
import os, subprocess, sys, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(tempfile.mkdtemp(prefix='aiedge-credential-test-'))
if os.name=='nt':
 import ctypes
 ctypes.windll.kernel32.SetErrorMode(3)
stubs=OUT/'stubs';(stubs/'mbedtls').mkdir(parents=True)
(stubs/'nvs.h').write_text('''#pragma once
#include <cstdint>
#include <cstddef>
using nvs_handle_t=int;
constexpr int ESP_OK=0,ESP_ERR_NVS_NOT_FOUND=1,NVS_READONLY=0,NVS_READWRITE=1;
int nvs_open(const char*,int,nvs_handle_t*);
int nvs_get_blob(nvs_handle_t,const char*,void*,size_t*);
int nvs_set_blob(nvs_handle_t,const char*,const void*,size_t);
int nvs_commit(nvs_handle_t);void nvs_close(nvs_handle_t);
''')
(stubs/'esp_random.h').write_text('#pragma once\nvoid esp_fill_random(void*,size_t);\n')
(stubs/'mbedtls/pkcs5.h').write_text('#pragma once\nconstexpr int MBEDTLS_MD_SHA256=6;\nint mbedtls_pkcs5_pbkdf2_hmac_ext(int,const unsigned char*,size_t,const unsigned char*,size_t,unsigned,uint32_t,unsigned char*);\n')
(stubs/'mbedtls/sha256.h').write_text('#pragma once\nint mbedtls_sha256(const unsigned char*,size_t,unsigned char*,int);\n')
cpp=OUT/'adapter.cpp';cpp.write_text(r'''
#include "WebsiteCredentialEsp.h"
#include <cassert>
#include <cstring>
using namespace AIEdgeAuth;
int opened=0,got=0,set=0,commit=0,closed=0,writes=0,commits=0,crypto=0;size_t returned=credentialBytes;
int nvs_open(const char*n,int mode,nvs_handle_t*h){assert(!strcmp(n,"aiedge_auth"));assert(mode==NVS_READONLY||mode==NVS_READWRITE);*h=4;return opened;}
int nvs_get_blob(nvs_handle_t h,const char*k,void*,size_t*n){assert(h==4&&!strcmp(k,"credential")&&*n==credentialBytes);*n=returned;return got;}
int nvs_set_blob(nvs_handle_t h,const char*k,const void*,size_t n){assert(h==4&&!strcmp(k,"credential")&&n==credentialBytes);++writes;return set;}
int nvs_commit(nvs_handle_t h){assert(h==4);++commits;return commit;}
void nvs_close(nvs_handle_t h){assert(h==4);++closed;}
void esp_fill_random(void*p,size_t n){memset(p,0x6a,n);}
int mbedtls_pkcs5_pbkdf2_hmac_ext(int type,const unsigned char*,size_t n,const unsigned char*,size_t salt,unsigned iterations,uint32_t length,unsigned char*){assert(type==MBEDTLS_MD_SHA256&&n==16&&salt==16&&iterations==20000&&length==32);return crypto;}
int mbedtls_sha256(const unsigned char*,size_t n,unsigned char*,int is224){assert(n==56&&!is224);return crypto;}
int main(){NvsBackend b;uint8_t record[credentialBytes]={};
 opened=ESP_ERR_NVS_NOT_FOUND;assert(b.read(record,sizeof record)==ReadResult::Missing&&closed==0);opened=9;assert(b.read(record,sizeof record)==ReadResult::Error&&closed==0);assert(!b.write(record,sizeof record)&&!writes);
 opened=0;got=ESP_ERR_NVS_NOT_FOUND;assert(b.read(record,sizeof record)==ReadResult::Missing&&closed==1);got=9;assert(b.read(record,sizeof record)==ReadResult::Error&&closed==2);got=0;
 for(auto n:{size_t(0),credentialBytes-1,credentialBytes+1}){returned=n;assert(b.read(record,sizeof record)==ReadResult::Error);}returned=credentialBytes;assert(b.read(record,sizeof record)==ReadResult::Present);
 int before=closed;set=9;assert(!b.write(record,sizeof record)&&commits==0&&closed==before+1);set=0;commit=9;assert(!b.write(record,sizeof record)&&commits==1);commit=0;assert(b.write(record,sizeof record)&&commits==2);
 assert(b.random(record,16)&&record[0]==0x6a);for(int failure:{0,9}){crypto=failure;assert(b.derive(record,16,record,record)==!failure);assert(b.digest(record,56,record)==!failure);}
}
''')
loader=(ROOT/'bootstrap/src/main.cpp').read_text()
block=loader[loader.index(' auto nvs=nvs_flash_init();'):loader.index(' ESP_ERROR_CHECK(esp_netif_init());')]
assert 'nvs_flash_erase' not in block
loader_cpp=OUT/'loader_nvs.cpp'
loader_cpp.write_text('#include <cassert>\n#include <cstdio>\nint error=0,calls=0;bool networkStarted=false;constexpr int ESP_OK=0;int nvs_flash_init(){++calls;return error;}const char*esp_err_to_name(int){return "test";}\nvoid boot(){'+block+'networkStarted=true;}\nint main(){for(int e:{0,1,2,3,100}){error=e;calls=0;networkStarted=false;boot();assert(calls==1&&networkStarted==(e==0));}}')
env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(OUT/'global'),ZIG_LOCAL_CACHE_DIR=str(OUT/'local'))
for source in [ROOT/'tools/auth-tests/credential_store_test.cpp',ROOT/'tools/auth-tests/website_access_test.cpp',cpp,loader_cpp]:
 exe=OUT/(source.stem+'.exe')
 subprocess.run([sys.executable,'-m','ziglang','c++','-std=c++11','-O2','-UNDEBUG','-include','initializer_list','-I'+str(stubs),'-I'+str(ROOT/'shared'),str(source),'-o',str(exe)],check=True,env=env)
 subprocess.run([str(exe)],check=True)
print('PASS: website access, credential state transitions, corruption/write faults, NVS/crypto adapter contracts and loader NVS error preservation; not hardware or cryptographic implementation validation')
