#pragma once
#include "ImageSpoolFile.h"
#include <dirent.h>

namespace ImageArchive {
// Recheck disk identity even after remote acknowledgment. A failed remove or
// verification leaves the queue slot occupied, never claiming successful cleanup.
template<class Hash>
SpoolResult removeAcknowledged(const std::string& root, UploadQueue& queue, const Ticket& ticket,std::string* releasedSettings=nullptr) {
    if(releasedSettings)releasedSettings->clear();
    if(!queue.acknowledged(ticket)) return SpoolResult::Conflict;
    const auto path=root+"/"+ticket.identity.capture+".spool";
    CaptureMetadata metadata;UploadRecord observed;
    const auto result=readSpoolFile<Hash>(path,metadata,observed);
    if(result!=SpoolResult::Saved) return result;
    if(!(observed.identity==ticket.identity)) return SpoolResult::Conflict;
    if(std::remove(path.c_str())!=0) return SpoolResult::IoError;
    if(!queue.release(ticket))return SpoolResult::Conflict;
    if(releasedSettings)*releasedSettings=metadata.settingsHash;
    return SpoolResult::Saved;
}
// Explicit recovery of a fully written temporary file. The same single-owner
// requirement as publication applies. Conflicts and damaged evidence remain.
template<class Hash>
SpoolResult promotePending(const std::string& root, const std::string& capture) {
    if(!validHash(capture)) return SpoolResult::Invalid;
    const auto path=root+"/"+capture+".spool";
    const auto pending=path+".pending";
    CaptureMetadata metadata;UploadRecord candidate,existing;
    auto result=readSpoolFile<Hash>(pending,metadata,candidate);
    if(result!=SpoolResult::Saved) return result;
    if(candidate.identity.capture!=capture) return SpoolResult::Conflict;
    result=readSpoolFile<Hash>(path,metadata,existing);
    if(result==SpoolResult::Saved)
        return candidate.identity==existing.identity ? SpoolResult::Duplicate : SpoolResult::Conflict;
    if(result!=SpoolResult::Missing) return result;
    if(std::rename(pending.c_str(),path.c_str())!=0) return SpoolResult::IoError;
    result=readSpoolFile<Hash>(path,metadata,existing);
    return result==SpoolResult::Saved && !(candidate.identity==existing.identity) ? SpoolResult::Conflict : result;
}
struct Recovery {
    bool complete=false;
    uint64_t diskBytes=0;
    uint32_t files=0, ready=0, partial=0, damaged=0, unexpected=0, overCapacity=0;
    bool canCapture(uint32_t imageBytes,uint32_t extraBytes=0,uint32_t extraFiles=0) const {
        return complete && imageBytes>0 && imageBytes<=2*1024*1024 &&
            files+extraFiles<UploadQueue::Capacity && diskBytes<=UploadQueue::ByteLimit &&
            static_cast<uint64_t>(imageBytes)+SpoolRecordBytes+extraBytes<=UploadQueue::ByteLimit-diskBytes;
    }
};
// Run only at startup or with the upload worker quiescent. No files are removed
// or modified. An incomplete scan leaves the caller's queue unchanged.
template<class Hash>
Recovery recoverSpool(const std::string& root, UploadQueue& queue) {
    Recovery report;UploadQueue recovered;
    DIR* directory=opendir(root.c_str());
    if(!directory) return report;
    bool ok=true;
    while(ok) {
        errno=0;
        auto* entry=readdir(directory);
        if(!entry) {if(errno)ok=false;break;}
        const std::string name=entry->d_name;
        if(name=="." || name=="..") continue;
        // Bound startup work even if this dedicated directory was misused.
        if(report.files>=32) {ok=false;break;}
        ++report.files;
        const auto path=root+"/"+name;
        struct stat info;
        if(stat(path.c_str(),&info)!=0 || info.st_size<0 || (info.st_mode&S_IFMT)!=S_IFREG) {
            ++report.unexpected;ok=false;break;
        }
        const auto size=static_cast<uint64_t>(info.st_size);
        if(size>std::numeric_limits<uint64_t>::max()-report.diskBytes) {ok=false;break;}
        report.diskBytes+=size;
        const bool final=name.size()==70 && name.substr(64)==".spool" && validHash(name.substr(0,64));
        const bool pending=name.size()==78 && name.substr(64)==".spool.pending" && validHash(name.substr(0,64));
        if(!final && !pending) {++report.unexpected;continue;}
        if(pending) {++report.partial;continue;}
        if(size<SpoolRecordBytes || size>SpoolRecordBytes+2*1024*1024) {++report.damaged;continue;}
        CaptureMetadata metadata;UploadRecord record;
        const auto result=readSpoolFile<Hash>(path,metadata,record);
        if(result==SpoolResult::IoError || result==SpoolResult::Missing) {ok=false;break;}
        if(result!=SpoolResult::Saved || record.identity.capture!=name.substr(0,64)) {++report.damaged;continue;}
        const auto admission=recovered.add(record.identity);
        if(admission==Admission::Added) ++report.ready;
        else if(admission==Admission::Full) ++report.overCapacity;
        else {++report.damaged;}
    }
    if(closedir(directory)!=0) ok=false;
    report.complete=ok;
    if(ok) queue=recovered;
    return report;
}
} // namespace ImageArchive
