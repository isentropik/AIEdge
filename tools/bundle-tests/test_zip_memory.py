"""Check ESP ZIP allocation policy, overflow and failed-realloc preservation."""
from pathlib import Path
import os,subprocess,sys,tempfile
root=Path(__file__).resolve().parents[2]
out=Path(tempfile.mkdtemp(prefix='aiedge-zip-memory-'))
(out/'esp_heap_caps.h').write_text('''#pragma once
#include <cstddef>
constexpr unsigned MALLOC_CAP_SPIRAM=1,MALLOC_CAP_8BIT=2;
void* heap_caps_malloc(size_t,unsigned);void* heap_caps_realloc(void*,size_t,unsigned);void heap_caps_free(void*);
''')
(out/'test.cpp').write_text(r'''
#define ESP_PLATFORM
#include "BundleZipMemory.h"
#include <cassert>
#include <cstdlib>
#include <cstring>
static unsigned calls=0;static bool fail=false;
void* heap_caps_malloc(size_t n,unsigned caps){assert(caps==(MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));++calls;return fail?nullptr:malloc(n);}
void* heap_caps_realloc(void*p,size_t n,unsigned caps){assert(caps==(MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));++calls;return fail?nullptr:realloc(p,n);}
void heap_caps_free(void*p){free(p);}
int main(){mz_zip_archive zip{};MeterBundle::configureZipMemory(zip);assert(zip.m_pAlloc&&zip.m_pRealloc&&zip.m_pFree);
 char*p=static_cast<char*>(zip.m_pAlloc(nullptr,4,8));assert(p);memset(p,42,32);
 unsigned before=calls;assert(!zip.m_pAlloc(nullptr,SIZE_MAX,2)&&calls==before);
 assert(!zip.m_pRealloc(nullptr,p,SIZE_MAX,2)&&calls==before&&p[0]==42);
 fail=true;assert(!zip.m_pRealloc(nullptr,p,1,64)&&p[31]==42);assert(!zip.m_pAlloc(nullptr,1,32));fail=false;
 p=static_cast<char*>(zip.m_pRealloc(nullptr,p,1,64));assert(p&&p[31]==42);zip.m_pFree(nullptr,p);zip.m_pFree(nullptr,nullptr);
}
''')
env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(out/'cache'),ZIG_LOCAL_CACHE_DIR=str(out/'local'))
exe=out/'test.exe'
subprocess.run([sys.executable,'-m','ziglang','c++','-std=c++11','-O2','-UNDEBUG','-I'+str(out),'-I'+str(root/'code/components/jomjol_fileserver_ota'),str(out/'test.cpp'),'-o',str(exe)],env=env,check=True)
subprocess.run([str(exe)],check=True)
print('PASS: ZIP allocator requests PSRAM only, rejects multiplication overflow and preserves failed reallocations; SDK heap is substituted')
