#pragma once
#include "ImageArchiveWorker.h"
#include "ImageArchiveSha.h"
#include "RawCaptureObserver.h"
#include <atomic>

namespace ImageArchive {
struct CaptureProfile {
    std::string device,boot,firmwareHash,modelHash,calibrationHash;
    int width=0,height=0;
};
struct CaptureBindingState {
    CaptureProfile profile;
    std::atomic<bool> configured{false},enabled{false};
    std::atomic<uint32_t> rejected{0};
};
inline CaptureBindingState& captureBinding(){static CaptureBindingState state;return state;}
// Profile identities describe the intended reader, not successful inference.
// A fresh boot ID must be supplied at every boot. Invalidate before reconfiguring
// model/geometry; changing this immutable profile requires controlled restart.
inline void disableCaptureArchive(){captureBinding().enabled.store(false,std::memory_order_release);}
inline void observeArchiveCapture(const unsigned char* bytes,size_t length,int64_t captureUs,
                                  int width,int height,const std::string& settings) {
    auto& state=captureBinding();if(!state.enabled.load(std::memory_order_acquire))return;
    const auto& profile=state.profile;
    if(!bytes || length==0 || length>2*1024*1024 || captureUs<=0 || width!=profile.width || height!=profile.height) {
        ++state.rejected;return;
    }
    CaptureMetadata m;m.device=profile.device;m.boot=profile.boot;m.firmwareHash=profile.firmwareHash;
    m.modelHash=profile.modelHash;m.calibrationHash=profile.calibrationHash;
    m.captureUs=static_cast<uint64_t>(captureUs);m.imageBytes=length;
    m.settingsHash=hashBytes<Sha256>(settings);
    if(!validSettingsDescriptor(m.settingsHash,settings,hashBytes<Sha256>)){++state.rejected;return;}
    Sha256 image;
    if(!image.update(bytes,length)){++state.rejected;return;}
    m.imageHash=image.finish();
    // UTC remains unknown until a validated capture-time clock mapping exists.
    if(!submitArchiveImage(m,bytes,length,settings))++state.rejected;
}
// Caller holds processing and camera guards. Never rewrites the immutable
// profile or swaps observers while captures can be active.
inline bool resumeCaptureArchive(const CaptureProfile& p){
    auto& s=captureBinding();const auto& old=s.profile;
    if(!s.configured.load(std::memory_order_acquire)||!archiveWorkerStatus().started||
       RawCaptureObserver::slot().load(std::memory_order_acquire)!=observeArchiveCapture||
       p.device!=old.device||p.boot!=old.boot||p.firmwareHash!=old.firmwareHash||
       p.modelHash!=old.modelHash||p.calibrationHash!=old.calibrationHash||
       p.width!=old.width||p.height!=old.height)return false;
    s.enabled.store(true,std::memory_order_release);return true;
}
inline bool bindCaptureArchive(const CaptureProfile& profile) {
    if(!validName(profile.device)||!validName(profile.boot)||!validHash(profile.firmwareHash)||
       !validHash(profile.modelHash)||!validHash(profile.calibrationHash)||
       profile.width<=0||profile.height<=0||profile.width>4096||profile.height>4096 ||
       !archiveWorkerStatus().started)return false;
    auto& state=captureBinding();
    if(state.configured.exchange(true,std::memory_order_acq_rel))return false;
    state.profile=profile;
    if(!RawCaptureObserver::install(observeArchiveCapture))return false;
    state.enabled.store(true,std::memory_order_release);return true;
}
}
