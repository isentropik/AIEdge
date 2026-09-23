#pragma once
#include "ImageSpoolRecord.h"
#include <cstdio>
#include <cerrno>
#include <fcntl.h>
#include <sys/stat.h>
#ifdef _WIN32
#include <io.h>
#else
#include <unistd.h>
#endif

namespace ImageArchive {
enum class SpoolResult { Saved, Duplicate, Missing, Invalid, Conflict, IoError, PendingExists };
template<class Hash> std::string hashBytes(const std::string& bytes) {
    Hash hash;
    return hash.update(reinterpret_cast<const unsigned char*>(bytes.data()),bytes.size()) ? hash.finish() : "";
}
inline int syncSpoolFile(FILE* f) {
#ifdef _WIN32
    return _commit(_fileno(f));
#else
    return fsync(fileno(f));
#endif
}
// Hash implements incremental update(bytes,size) -> bool and finish() -> hex.
// Its errors must yield an empty hash, never a fabricated digest.
template<class Hash>
SpoolResult readSpoolFile(const std::string& path, CaptureMetadata& metadata, UploadRecord& record) {
    metadata=CaptureMetadata{};record=UploadRecord{};
    FILE* f=std::fopen(path.c_str(),"rb");
    if(!f) return errno==ENOENT ? SpoolResult::Missing : SpoolResult::IoError;
    CaptureMetadata m; UploadRecord r;
    std::string header(SpoolRecordBytes,'\0');
    bool ok=std::fread(&header[0],1,header.size(),f)==header.size();
    if(ok) ok=decodeSpoolRecord(header,hashBytes<Hash>,m);
    Hash image;
    unsigned char buffer[4096];
    uint32_t remaining=ok ? m.imageBytes : 0;
    while(ok && remaining) {
        const size_t count=remaining>sizeof(buffer) ? sizeof(buffer) : remaining;
        ok=std::fread(buffer,1,count,f)==count && image.update(buffer,count);
        remaining-=static_cast<uint32_t>(count);
    }
    if(ok) ok=std::fgetc(f)==EOF && !std::ferror(f) && image.finish()==m.imageHash;
    const bool ioError=std::ferror(f)!=0;
    const bool closeOk=std::fclose(f)==0;
    if(ioError || !closeOk) return SpoolResult::IoError;
    if(!ok || !buildRecord(m,hashBytes<Hash>,r)) return SpoolResult::Invalid;
    metadata=m;record=r;
    return SpoolResult::Saved;
}

// A single spool owner must serialize this with recovery, upload and deletion.
// Root must already exist and be dedicated to the spool. Admission/capacity
// accounting must occur before this function; this does not evict any file.
template<class Hash>
SpoolResult writeSpoolFile(const std::string& root, const CaptureMetadata& metadata,
                          const unsigned char* image, size_t length) {
    UploadRecord intended;
    if(!image || !validMetadata(metadata) || length!=metadata.imageBytes ||
       !buildRecord(metadata,hashBytes<Hash>,intended)) return SpoolResult::Invalid;
    Hash imageHash;
    if(!imageHash.update(image,length) || imageHash.finish()!=metadata.imageHash) return SpoolResult::Invalid;
    const auto path=root+"/"+intended.identity.capture+".spool";
    CaptureMetadata existing;UploadRecord observed;
    auto status=readSpoolFile<Hash>(path,existing,observed);
    if(status==SpoolResult::Saved)
        return observed.identity==intended.identity ? SpoolResult::Duplicate : SpoolResult::Conflict;
    if(status!=SpoolResult::Missing) return status;
    const auto pending=path+".pending";
    // Never truncate a leftover file: recovery must account for it explicitly.
    const int fd=open(pending.c_str(),O_WRONLY|O_CREAT|O_EXCL
#ifdef _WIN32
                      |O_BINARY
#endif
                      ,0600);
    if(fd<0) return errno==EEXIST ? SpoolResult::PendingExists : SpoolResult::IoError;
    FILE* f=fdopen(fd,"wb");
    if(!f) {close(fd);return SpoolResult::IoError;}
    const auto header=encodeSpoolRecord(metadata,hashBytes<Hash>);
    bool ok=header.size()==SpoolRecordBytes && std::fwrite(header.data(),1,header.size(),f)==header.size();
    if(ok) ok=std::fwrite(image,1,length,f)==length;
    if(ok) ok=std::fflush(f)==0 && syncSpoolFile(f)==0;
    if(std::fclose(f)!=0) ok=false;
    if(!ok) return SpoolResult::IoError; // preserve failure evidence
    status=readSpoolFile<Hash>(pending,existing,observed);
    if(status!=SpoolResult::Saved) return status;
    if(!(observed.identity==intended.identity)) return SpoolResult::Conflict;
    // Single owner guarantees no writer creates the final path between checks.
    struct stat info;
    if(stat(path.c_str(),&info)==0) return SpoolResult::Conflict;
    if(errno!=ENOENT || std::rename(pending.c_str(),path.c_str())!=0) return SpoolResult::IoError;
    status=readSpoolFile<Hash>(path,existing,observed);
    return status==SpoolResult::Saved && !(observed.identity==intended.identity) ? SpoolResult::Conflict : status;
}
} // namespace ImageArchive
