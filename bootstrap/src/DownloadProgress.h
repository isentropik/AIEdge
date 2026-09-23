#pragma once
#include <algorithm>
#include <cstdint>

namespace AIEdgeDownload {
enum class Timeout { None, Stalled, Overall };
inline Timeout timeout(uint32_t elapsedMs, uint32_t idleMs) {
    if (elapsedMs >= 600000) return Timeout::Overall;
    if (idleMs >= 30000) return Timeout::Stalled;
    return Timeout::None;
}
struct Progress {
    unsigned bytes = 0;
    uint32_t startedMs = 0;
    uint32_t lastByteMs = 0;
    bool started = false;
    void begin(uint32_t now) { bytes = 0; startedMs = lastByteMs = now; started = true; }
    void received(unsigned count, uint32_t now) { bytes = count; lastByteMs = now; }
};
struct View {
    double percent = 0, elapsedSeconds = 0, averageBytesPerSecond = 0;
    double remainingSeconds = -1; // Unavailable, not zero seconds remaining.
    bool waitingForData = false;
};
inline View view(const Progress& progress, unsigned total, uint32_t now, bool downloading) {
    View result;
    if (!total) return result;
    const auto bytes = std::min(progress.bytes, total);
    result.percent = 100.0 * bytes / total;
    if (!progress.started || !downloading) return result;
    // Unsigned subtraction remains valid across the millisecond counter wrap.
    const uint32_t elapsed = now - progress.startedMs;
    result.elapsedSeconds = elapsed / 1000.0;
    result.waitingForData = bytes < total && now - progress.lastByteMs >= 10000;
    if (elapsed > 0) result.averageBytesPerSecond = bytes * 1000.0 / elapsed;
    if (elapsed >= 3000 && bytes > 0 && !result.waitingForData)
        result.remainingSeconds = (total - bytes) / result.averageBytesPerSecond;
    return result;
}
}
