#pragma once
#include <atomic>

// No waiting and no recursion: callers must acquire processing before camera
// access, and release both before invoking another controller entry point.
class ProcessingAccess {
    static std::atomic_flag& flag() {
        static std::atomic_flag value = ATOMIC_FLAG_INIT;
        return value;
    }
    bool acquired;
public:
    ProcessingAccess(): acquired(!flag().test_and_set(std::memory_order_acquire)) {}
    ~ProcessingAccess() { if (acquired) flag().clear(std::memory_order_release); }
    explicit operator bool() const { return acquired; }
    ProcessingAccess(const ProcessingAccess&) = delete;
    ProcessingAccess& operator=(const ProcessingAccess&) = delete;
};
