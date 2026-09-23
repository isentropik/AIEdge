#pragma once
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <string>

// Startup-only observer for a successfully decoded, timestamped live frame.
// The callback borrows the original camera bytes only for this call. It must
// copy if needed and must not perform disk/network IO or alter camera settings.
namespace RawCaptureObserver {
using Callback=void(*)(const unsigned char*,size_t,int64_t,int,int,const std::string&);
inline std::atomic<Callback>& slot(){static std::atomic<Callback> callback{nullptr};return callback;}
inline bool install(Callback callback){
    if(!callback)return false;
    Callback expected=nullptr;
    return slot().compare_exchange_strong(expected,callback,std::memory_order_release,std::memory_order_relaxed);
}
inline bool enabled(){return slot().load(std::memory_order_acquire)!=nullptr;}
inline void notify(const unsigned char* bytes,size_t length,int64_t captureUs,int width,int height,const std::string& settings){
    if(!bytes || !length || captureUs<=0 || width<=0 || height<=0)return;
    auto callback=slot().load(std::memory_order_acquire);
    if(callback && !settings.empty())callback(bytes,length,captureUs,width,height,settings);
}
}
