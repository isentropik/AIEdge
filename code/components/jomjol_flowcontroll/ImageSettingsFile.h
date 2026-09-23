#pragma once
#include "ImageSpoolFile.h"
#include "ImageSettingsDescriptor.h"

namespace ImageArchive {
template<class Hash>
SpoolResult readSettingsPath(const std::string& path,const std::string& hash,std::string& out) {
    out.clear();if(!validHash(hash))return SpoolResult::Invalid;
    FILE* f=std::fopen(path.c_str(),"rb");
    if(!f)return errno==ENOENT ? SpoolResult::Missing : SpoolResult::IoError;
    std::string data;char buffer[512];bool ok=true;
    for(;;) {
        const auto count=std::fread(buffer,1,sizeof(buffer),f);
        data.append(buffer,count);
        if(data.size()>MaxSettingsBytes){ok=false;break;}
        if(count<sizeof(buffer))break;
    }
    const bool failed=std::ferror(f)!=0;
    const bool closed=std::fclose(f)==0;
    if(failed || !closed)return SpoolResult::IoError;
    if(!ok || !validSettingsDescriptor(hash,data,hashBytes<Hash>))return SpoolResult::Invalid;
    out=data;return SpoolResult::Saved;
}
template<class Hash>
SpoolResult readSettingsFile(const std::string& root,const std::string& hash,std::string& out) {
    if(!validHash(hash)){out.clear();return SpoolResult::Invalid;}
    return readSettingsPath<Hash>(root+"/"+hash+".settings",hash,out);
}
// Same single-owner and directory durability limitations as image publication.
// Capacity must include these files and any .pending files before admission.
template<class Hash>
SpoolResult writeSettingsFile(const std::string& root,const std::string& hash,const std::string& descriptor) {
    if(!validSettingsDescriptor(hash,descriptor,hashBytes<Hash>))return SpoolResult::Invalid;
    std::string existing;auto result=readSettingsFile<Hash>(root,hash,existing);
    if(result==SpoolResult::Saved)return existing==descriptor ? SpoolResult::Duplicate : SpoolResult::Conflict;
    if(result!=SpoolResult::Missing)return result;
    const auto final=root+"/"+hash+".settings",pending=final+".pending";
    // A complete interrupted write is recoverable; a partial one stays intact.
    result=readSettingsPath<Hash>(pending,hash,existing);
    if(result==SpoolResult::Missing) {
        const int fd=open(pending.c_str(),O_WRONLY|O_CREAT|O_EXCL
#ifdef _WIN32
                          |O_BINARY
#endif
                          ,0600);
        if(fd<0)return errno==EEXIST ? SpoolResult::PendingExists : SpoolResult::IoError;
        bool ok=writeSpoolBytes(fd,descriptor.data(),descriptor.size());
        if(ok)ok=syncSpoolDescriptor(fd)==0;
        if(close(fd)!=0)ok=false;
        if(!ok)return SpoolResult::IoError;
        result=readSettingsPath<Hash>(pending,hash,existing);
    }
    if(result!=SpoolResult::Saved)return result;
    if(existing!=descriptor)return SpoolResult::Conflict;
    struct stat info;
    if(stat(final.c_str(),&info)==0)return SpoolResult::Conflict;
    if(errno!=ENOENT || std::rename(pending.c_str(),final.c_str())!=0)return SpoolResult::IoError;
    return readSettingsFile<Hash>(root,hash,existing);
}
}
