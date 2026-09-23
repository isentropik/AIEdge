// Host-only fault injection against the production archive implementation.
#include <cstdio>
#include <cerrno>
#include <fcntl.h>
#include <sys/stat.h>
#ifdef _WIN32
#include <io.h>
#include <direct.h>
#else
#include <unistd.h>
#endif
#include <cassert>
#include <fstream>
#include <iostream>
#include <string>

namespace Fault {
enum Mode { None, Write, Sync, Close };
Mode mode=None;
size_t remaining=0;
int opened=-1,closed=-1;
auto output(int fd,const void* bytes,size_t count)->decltype(::write(fd,bytes,count)) {
    opened=fd;
    if(mode==Write) {
        if(!remaining){errno=ENOSPC;return -1;}
        if(count>remaining)count=remaining;
        remaining-=count;
    }
    return ::write(fd,bytes,count);
}
int sync(int fd) {
    if(mode==Sync){errno=EIO;return -1;}
#ifdef _WIN32
    return ::_commit(fd);
#else
    return ::fsync(fd);
#endif
}
int close(int fd) {
    closed=fd;const int result=::close(fd);
    if(mode==Close){errno=EIO;return -1;}
    return result;
}
}
// System declarations are already included. Only archive writes are intercepted.
#define write Fault::output
#define close Fault::close
#ifdef _WIN32
#define _commit Fault::sync
#else
#define fsync Fault::sync
#endif
// Reintroducing fdopen must fail compilation: FAT lacks its fcntl dependency.
#define fdopen archive_fdopen_is_not_supported
#include "ImageSettingsFile.h"
#include "ImageArchiveEngine.h"
#undef write
#undef close
#undef _commit
#undef fsync
#undef fdopen
#include "ImageArchiveSha.h"
using namespace ImageArchive;

bool exists(const std::string& p){struct stat st{};return stat(p.c_str(),&st)==0;}
std::string read(const std::string& p){std::ifstream f(p,std::ios::binary);return {std::istreambuf_iterator<char>(f),{}};}
void directory(const std::string& p){
#ifdef _WIN32
    assert(_mkdir(p.c_str())==0);
#else
    assert(mkdir(p.c_str(),0700)==0);
#endif
}
int main(int argc,char** argv) {
    assert(argc==2);const std::string root=argv[1];
    const std::string settings="capture-settings-v1\nsource=fault-injection\n";
    const std::string image(9001,'j');CaptureMetadata m;
    m.device="test";m.boot="boot";m.captureUs=1;m.imageBytes=image.size();
    m.imageHash=hashBytes<Sha256>(image);m.settingsHash=hashBytes<Sha256>(settings);
    m.firmwareHash=std::string(64,'1');m.modelHash=std::string(64,'2');m.calibrationHash=std::string(64,'3');
    UploadRecord record;assert(buildRecord(m,hashBytes<Sha256>,record));
    int cases=0;
    for(bool settingsFile:{true,false})for(auto mode:{Fault::Write,Fault::Sync,Fault::Close}) {
        const auto dir=root+"/case-"+std::to_string(cases++);directory(dir);
        const auto final=dir+"/"+(settingsFile?m.settingsHash+".settings":record.identity.capture+".spool");
        Fault::mode=mode;Fault::remaining=settingsFile?7:SpoolRecordBytes+17;
        Fault::opened=Fault::closed=-1;
        const auto result=settingsFile?writeSettingsFile<Sha256>(dir,m.settingsHash,settings):
            writeSpoolFile<Sha256>(dir,m,reinterpret_cast<const unsigned char*>(image.data()),image.size());
        assert(result==SpoolResult::IoError);assert(!exists(final));assert(exists(final+".pending"));
        assert(Fault::opened>=0 && Fault::closed==Fault::opened);
        const auto preserved=read(final+".pending");assert(!preserved.empty());
        Fault::mode=Fault::None;
        // Failed/partial evidence is never silently overwritten on a retry.
        const auto retry=settingsFile?writeSettingsFile<Sha256>(dir,m.settingsHash,settings):
            promotePending<Sha256>(dir,record.identity.capture);
        if(mode==Fault::Write) {
            assert(retry!=SpoolResult::Saved && retry!=SpoolResult::Duplicate);
            assert(!exists(final));assert(read(final+".pending")==preserved);
        } else {
            // A fully written pending file may recover only after full readback.
            assert(retry==SpoolResult::Saved);assert(exists(final));
        }
    }
    const auto dir=root+"/engine";directory(dir);ArchiveEngine<Sha256> engine;
    assert(engine.start(dir));Fault::mode=Fault::Sync;
    assert(engine.enqueue(m,reinterpret_cast<const unsigned char*>(image.data()),image.size(),settings)==EnqueueResult::StorageFailed);
    const auto status=engine.status();assert(status.stored==0 && status.pending==0 && status.rejected==1);
    Fault::mode=Fault::None;
    std::cout<<cases<<" file faults and engine rejection passed; incomplete files retained, no false saved state\n";
}
