#pragma once
#include <cstdint>
#include "freertos/FreeRTOS.h"
#include "esp_timer.h"
#include "ProcessingAccess.h"

namespace CycleTelemetry {
constexpr int maxStages = 16;
constexpr int64_t targetUs = 30000000;
struct Stage { int index = -1; int64_t durationUs = 0; bool ok = false; };
struct Record {
    int64_t startedUs = 0, finishedUs = 0, capturedUs = 0, captureIntervalUs = 0;
    bool pipelineCompleted = false, readerAccepted = false;
    int attempts = 0, storedStages = 0;
    Stage stages[maxStages];
};
struct Snapshot {
    bool active = false;
    uint64_t attempts = 0, completed = 0, failed = 0, overlapsRejected = 0, overTarget = 0;
    uint64_t missedScheduleSlots = 0, acceptedReaderCycles = 0, acceptedReaderStreak = 0;
    int64_t previousCaptureUs = 0;
    Record last;
};
inline Snapshot& state() { static Snapshot value; return value; }
inline portMUX_TYPE& mutex() { static portMUX_TYPE value = portMUX_INITIALIZER_UNLOCKED; return value; }
inline Snapshot snapshot() {
    portENTER_CRITICAL(&mutex());
    Snapshot result = state();
    portEXIT_CRITICAL(&mutex());
    return result;
}
inline void schedule(uint64_t missed) {
    portENTER_CRITICAL(&mutex());
    state().missedScheduleSlots += missed;
    portEXIT_CRITICAL(&mutex());
}
class Span {
    ProcessingAccess processing;
    bool acquired = false, finished = false;
    Record record;
public:
    Span() {
        record.startedUs = esp_timer_get_time();
        portENTER_CRITICAL(&mutex());
        if (!processing || state().active) ++state().overlapsRejected;
        else { state().active = true; ++state().attempts; acquired = true; }
        portEXIT_CRITICAL(&mutex());
    }
    ~Span() { if (acquired && !finished) finish(false); }
    explicit operator bool() const { return acquired; }
    void stage(int index, int64_t start, bool ok) {
        ++record.attempts;
        if (record.storedStages < maxStages) {
            Stage& entry = record.stages[record.storedStages++];
            entry.index = index; entry.durationUs = esp_timer_get_time()-start; entry.ok = ok;
        }
    }
    void capture(int64_t time) {
        if (acquired && !finished && time > 0 && time >= record.startedUs &&
            time <= esp_timer_get_time()) record.capturedUs = time;
    }
    void readerAccepted() {
        if(acquired && !finished && record.capturedUs>0)record.readerAccepted=true;
    }
    void finish(bool complete) {
        if (!acquired || finished) return;
        record.finishedUs = esp_timer_get_time();
        record.pipelineCompleted = complete;
        portENTER_CRITICAL(&mutex());
        if (record.capturedUs > state().previousCaptureUs) {
            if (state().previousCaptureUs > 0)
                record.captureIntervalUs = record.capturedUs-state().previousCaptureUs;
            state().previousCaptureUs = record.capturedUs;
        }
        if(complete && record.readerAccepted){
            ++state().acceptedReaderCycles;
            if(state().acceptedReaderStreak<UINT64_MAX)++state().acceptedReaderStreak;
        } else state().acceptedReaderStreak=0;
        if (complete) ++state().completed; else ++state().failed;
        if (record.finishedUs-record.startedUs > targetUs) ++state().overTarget;
        state().last = record;
        state().active = false;
        portEXIT_CRITICAL(&mutex());
        finished = true;
    }
    Span(const Span&) = delete;
    Span& operator=(const Span&) = delete;
};
}
