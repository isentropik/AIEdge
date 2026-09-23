#pragma once
#include <atomic>

namespace StreamPreview {
// -1 inherits the saved capture intensity. This state is never persisted.
inline std::atomic<int>& value() { static std::atomic<int> setting{-1}; return setting; }
inline int get() { return value().load(); }
inline void reset() { value().store(-1); }
inline bool set(int percent) {
    if (percent < 0 || percent > 100) return false;
    value().store(percent);
    return true;
}
inline bool parse(const char* text, int& percent) {
    if (!text || !*text) return false;
    int result = 0;
    for (const char* p = text; *p; ++p) {
        if (*p < '0' || *p > '9') return false;
        result = result * 10 + (*p - '0');
        if (result > 100) return false;
    }
    percent = result;
    return true;
}
}
