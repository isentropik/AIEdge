#pragma once
#include "ImageArchiveConfigFile.h"
#include "ImageArchiveDestination.h"
#include "ImageArchiveSha.h"
#include "CaptureArchiveBinding.h"
#include "PolarIdentity.h"
#include "esp_ota_ops.h"
#include "esp_partition.h"
#include "esp_system.h"
#include "esp_random.h"
#include <sys/stat.h>

namespace ImageArchive {
inline std::string archiveHex(const unsigned char* bytes,size_t size){
    const char* hex="0123456789abcdef";std::string result;result.reserve(size*2);
    for(size_t i=0;i<size;++i){result+=hex[bytes[i]>>4];result+=hex[bytes[i]&15];}
    return result;
}
// Caller holds processing and camera guards. Normal capture requires flow/GPIO
// initialization. Recovery-only mode never installs or enables a capture observer.
// Identical configuration may resume capture after reload; destination/profile
// changes never retarget an existing worker or its queued records.
inline const char* startConfiguredArchive(bool frozenProfile,bool recoveryOnly=false) {
    static bool workerStarted=false,captureBound=false;
    static Destination activeDestination;
    static CaptureProfile activeProfile;
    disableCaptureArchive(); // Fail closed even when called outside InitFlow.
    StartupConfig config;Destination destination;
    const auto loaded=loadArchiveConfig("/sdcard/config",config,destination);
    if(loaded==ConfigLoad::Disabled)return workerStarted?"Image archive capture disabled; queued uploads retain their existing destination":"Image archive disabled";
    if(loaded!=ConfigLoad::Ready)return "Image archive configuration could not be loaded";
    if(!frozenProfile && !recoveryOnly)return "Image archive requires the configured frozen PolarV1 profile";
    if(workerStarted){
        if(config.device!=activeProfile.device||destination.host!=activeDestination.host||
           destination.port!=activeDestination.port||destination.timeoutMs!=activeDestination.timeoutMs||
           destination.token!=activeDestination.token||destination.certificatePem!=activeDestination.certificatePem)
            return "Archive destination or identity changed; restart required, existing queue destination unchanged";
        if(recoveryOnly)return "Image archive queued-upload recovery active; capture disabled";
        if(!captureBound){
            captureBound=true;
            return bindCaptureArchive(activeProfile)?"Image archive capture bound after queued-upload recovery":
                "Image archive capture binding failed";
        }
        return resumeCaptureArchive(activeProfile)?"Image archive capture resumed with unchanged destination":
            "Image archive capture could not resume";
    }
    unsigned char digest[32];const auto* partition=esp_ota_get_running_partition();
    if(!partition||esp_partition_get_sha256(partition,digest)!=ESP_OK)return "Image archive firmware identity unavailable";
    CaptureProfile profile;profile.device=config.device;profile.firmwareHash=archiveHex(digest,32);
    unsigned char nonce[16];esp_fill_random(nonce,sizeof(nonce));profile.boot=archiveHex(nonce,sizeof(nonce));
    profile.modelHash=polar::modelIdentity;profile.calibrationHash=polar::geometryIdentity;
    profile.width=640;profile.height=480;
    const auto key=archiveQueueKey<Sha256>(destination,config.device);
    if(key.size()!=64)return "Image archive destination identity unavailable";
    const std::string base="/sdcard/image-archive",root=base+"/"+key;
    // Never scan the legacy unbound root or a different destination's queue.
    // Preserve those files for explicit recovery; they have no proven owner.
    for(const auto& directory:{base,root}) {
        if(mkdir(directory.c_str(),0700)!=0&&errno!=EEXIST)return "Image archive spool directory unavailable";
        struct stat info{};
        if(stat(directory.c_str(),&info)!=0||!S_ISDIR(info.st_mode))return "Image archive spool path is not a directory";
    }
    if(!startArchiveWorker(root,destination))return "Image archive worker could not start";
    activeDestination=destination;activeProfile=profile;workerStarted=true;
    if(recoveryOnly)return "Image archive queued-upload recovery started; capture disabled, connectivity not yet verified";
    captureBound=true; // Binding may install immutable state even if it reports failure.
    if(!bindCaptureArchive(profile))return "Image archive capture binding failed";
    return "Image archive worker started; recovery and connectivity not yet verified";
}
}
