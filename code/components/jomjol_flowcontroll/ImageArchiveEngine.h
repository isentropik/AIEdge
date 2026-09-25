#pragma once
#include "ImageSpoolRecovery.h"
#include "ImageArchiveTransport.h"
#include "ImageSettingsFile.h"
#include "ImageSettingsCleanup.h"

namespace ImageArchive {
enum class EnqueueResult { Stored, Duplicate, NotReady, Full, Invalid, StorageFailed };
struct EngineStatus {
    bool ready=false;
    uint64_t stored=0, uploaded=0, rejected=0, failures=0, cleanupFailures=0, settingsCleanupDeferred=0;
    uint32_t pending=0, blocked=0, acknowledged=0;
    Recovery recovery;
    unsigned lastHttpStatus=0;
    uint64_t lastAttemptMs=0;
    const char* lastUploadError="not_started";
};
// All methods belong to one worker. Capture callbacks must hand off owned bytes
// to that worker, never call this concurrently with network/disk operations.
template<class Hash> class ArchiveEngine {
    std::string root;
    UploadQueue queue;
    EngineStatus state;
    void cleanup(const Ticket& ticket) {
        std::string settingsHash;
        if(removeAcknowledged<Hash>(root,queue,ticket,&settingsHash)!=SpoolResult::Saved){++state.cleanupFailures;return;}
        const auto result=pruneSettings<Hash>(root,settingsHash);
        if(result==SettingsCleanup::Uncertain || result==SettingsCleanup::IoError)++state.settingsCleanupDeferred;
    }
    void recount() {
        state.pending=state.blocked=state.acknowledged=0;
        for(const auto& e:queue.status()) {
            if(e.state==State::Pending || e.state==State::Uploading)++state.pending;
            if(e.state==State::Blocked)++state.blocked;
            if(e.state==State::Acknowledged)++state.acknowledged;
        }
    }
public:
    bool start(const std::string& directory) {
        if(state.ready) return false;
        root=directory;state.recovery=recoverSpool<Hash>(root,queue);
        state.ready=state.recovery.complete;recount();return state.ready;
    }
    EnqueueResult enqueue(const CaptureMetadata& metadata,const unsigned char* image,size_t length,const std::string& settings) {
        if(!state.ready){++state.rejected;return EnqueueResult::NotReady;}
        UploadRecord r;
        if(!image || length!=metadata.imageBytes || !validSettingsDescriptor(metadata.settingsHash,settings,hashBytes<Hash>) || !buildRecord(metadata,hashBytes<Hash>,r)) {
            ++state.rejected;return EnqueueResult::Invalid;
        }
        Hash inputHash;
        if(!inputHash.update(image,length) || inputHash.finish()!=metadata.imageHash) {
            ++state.rejected;return EnqueueResult::Invalid;
        }
        for(const auto& e:queue.status()) if(e.state!=State::Empty && e.identity.capture==r.identity.capture) {
            if(e.identity==r.identity) {
                std::string persisted;
                if(readSettingsFile<Hash>(root,metadata.settingsHash,persisted)==SpoolResult::Saved && persisted==settings)
                    return EnqueueResult::Duplicate;
                ++state.rejected;return EnqueueResult::StorageFailed;
            }
            ++state.rejected;return EnqueueResult::Invalid;
        }
        // Fresh accounting includes interrupted and externally added files. Do
        // not replace the live queue: doing so would erase backoff/blocked state.
        UploadQueue inventory;
        state.recovery=recoverSpool<Hash>(root,inventory);
        if(!state.recovery.complete){state.ready=false;++state.rejected;return EnqueueResult::StorageFailed;}
        std::string persisted;
        const auto existingSettings=readSettingsFile<Hash>(root,metadata.settingsHash,persisted);
        if(existingSettings!=SpoolResult::Saved && existingSettings!=SpoolResult::Missing){++state.rejected;return EnqueueResult::StorageFailed;}
        const bool newSettings=existingSettings==SpoolResult::Missing;
        if(!state.recovery.canCapture(metadata.imageBytes,newSettings?settings.size():0,newSettings?1:0)){++state.rejected;return EnqueueResult::Full;}
        const auto settingsSaved=writeSettingsFile<Hash>(root,metadata.settingsHash,settings);
        if(settingsSaved!=SpoolResult::Saved && settingsSaved!=SpoolResult::Duplicate){++state.rejected;return EnqueueResult::StorageFailed;}
        const auto saved=writeSpoolFile<Hash>(root,metadata,image,length);
        if(saved!=SpoolResult::Saved && saved!=SpoolResult::Duplicate){++state.rejected;return EnqueueResult::StorageFailed;}
        const auto added=queue.add(r.identity);
        if(added!=Admission::Added && added!=Admission::Duplicate) {
            // The verified file remains on disk for subsequent recovery.
            state.ready=false;++state.rejected;return EnqueueResult::StorageFailed;
        }
        ++state.stored;recount();
        return saved==SpoolResult::Duplicate ? EnqueueResult::Duplicate : EnqueueResult::Stored;
    }
    template<class Clock,class Upload>
    bool step(Clock now,Upload upload) {
        if(!state.ready) return false;
        // Retry local cleanup separately; never resend a verified acknowledgment
        // merely because removal failed in this running process.
        bool cleaned=false;
        for(size_t i=0;i<queue.status().size();++i) {
            const auto& e=queue.status()[i];
            if(e.state!=State::Acknowledged)continue;
            Ticket ticket;ticket.slot=i;ticket.serial=e.serial;ticket.identity=e.identity;
            cleanup(ticket);
            cleaned=true;
        }
        recount();
        Ticket ticket;if(!queue.begin(now(),ticket))return cleaned;
        const auto attempt=upload(root,ticket);
        const auto finished=now();
        state.lastAttemptMs=finished;
        state.lastHttpStatus=attempt.status>=100 && attempt.status<=599?static_cast<unsigned>(attempt.status):0;
        state.lastUploadError=uploadErrorCode(attempt.error);
        if(!queue.finish(ticket,finished,attempt.status,attempt.receipt)){
            state.lastUploadError="queue_transition_failed";state.ready=false;++state.failures;return false;
        }
        if(queue.acknowledged(ticket)) {
            state.lastUploadError="none";
            ++state.uploaded;
            cleanup(ticket);
        } else {
            if(!attempt.error)state.lastUploadError=(attempt.status==200 || attempt.status==201)?"receipt_invalid":"server_rejected";
            ++state.failures;
        }
        recount();return true;
    }
    EngineStatus status() const {return state;}
};
}
