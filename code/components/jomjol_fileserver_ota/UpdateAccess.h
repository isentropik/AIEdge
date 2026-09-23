#pragma once
#include <atomic>
// Serialize all flash transactions, including inherited OTA callers.
class UpdateAccess {
 static std::atomic_flag& flag(){static std::atomic_flag f=ATOMIC_FLAG_INIT;return f;}
 bool acquired;
public:
 UpdateAccess():acquired(!flag().test_and_set(std::memory_order_acquire)){}
 ~UpdateAccess(){if(acquired)flag().clear(std::memory_order_release);}
 explicit operator bool()const{return acquired;}
 UpdateAccess(const UpdateAccess&)=delete;
 UpdateAccess& operator=(const UpdateAccess&)=delete;
};
