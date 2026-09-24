"""Actual staging-directory recovery on temporary host storage; no device IO."""
from pathlib import Path
import os, subprocess, sys, tempfile
root=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='aiedge-pending-') as folder:
 out=Path(folder)
 (out/'test.cpp').write_text(r'''
#include <filesystem>
#include <fstream>
#include <cassert>
#ifdef _WIN32
#include <direct.h>
#define mkdir(path,mode) _mkdir(path)
#endif
#include "PendingBundleRecovery.h"
namespace fs=std::filesystem;
std::string read(const fs::path&p){std::ifstream f(p);return {std::istreambuf_iterator<char>(f),{}};}
int main(int argc,char**argv){
 assert(argc==2);fs::path base=argv[1];fs::create_directories(base/"pending");
 const std::string id(64,'a');auto pending=base/"pending"/id;
 using MeterBundle::preparePending;using R=MeterBundle::PendingRecovery;
 assert(preparePending(base.string(),id)==R::Ready);
 for(int i=0;i<32;++i){
  std::ofstream(pending/"partial.bin")<<"original-"<<i;
  assert(preparePending(base.string(),id)==R::Ready);
  assert(fs::is_empty(pending));
  assert(read(base/"interrupted"/(id+"-"+std::to_string(i))/"partial.bin")=="original-"+std::to_string(i));
 }
 std::ofstream(pending/"partial.bin")<<"last";
 assert(preparePending(base.string(),id)==R::Conflict);
 assert(read(pending/"partial.bin")=="last");
 const std::string fileId(64,'b');std::ofstream(base/"pending"/fileId)<<"keep";
 assert(preparePending(base.string(),fileId)==R::Conflict);
 assert(read(base/"pending"/fileId)=="keep");
 fs::path blocked=base/"blocked";fs::create_directories(blocked/"pending"/id);
 std::ofstream(blocked/"interrupted")<<"not a directory";
 std::ofstream(blocked/"pending"/id/"partial.bin")<<"preserve";
 assert(preparePending(blocked.string(),id)==R::IoError);
 assert(read(blocked/"pending"/id/"partial.bin")=="preserve");
}
''')
 env=dict(os.environ,ZIG_GLOBAL_CACHE_DIR=str(out/'cache'),ZIG_LOCAL_CACHE_DIR=str(out/'local'))
 exe=out/'test.exe'
 subprocess.run([sys.executable,'-m','ziglang','c++','-std=c++17','-O2','-UNDEBUG',
  '-I'+str(root/'code/components/jomjol_fileserver_ota'),str(out/'test.cpp'),'-o',str(exe)],env=env,check=True)
 subprocess.run([str(exe),str(out/'data')],check=True)
 print('PASS: fresh directory, 32 preserved retries, retention limit, file conflict and blocked recovery directory')
