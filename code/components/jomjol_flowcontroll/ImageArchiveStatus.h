#pragma once
#include "ImageArchiveWorker.h"
namespace ImageArchive {
// Snapshot-only diagnostics: no disk/network access, destination or credentials.
inline std::string archiveStatusJson(const WorkerStatus& status,bool captureEnabled,uint32_t bindingRejected) {
    const auto& e=status.engine;const auto& r=e.recovery;
    std::string result="{\"version\":1";
    auto flag=[&](const char* key,bool value){result+=",\""+std::string(key)+"\":"+(value?"true":"false");};
    auto number=[&](const char* key,uint64_t value){result+=",\""+std::string(key)+"\":"+std::to_string(value);};
    flag("worker_started",status.started);flag("capture_enabled",captureEnabled);flag("engine_ready",e.ready);
    number("handed_off",status.handedOff);number("handoff_rejected",status.dropped);number("binding_rejected",bindingRejected);
    number("stored",e.stored);number("upload_acknowledgments",e.uploaded);number("enqueue_rejected",e.rejected);
    number("upload_failures",e.failures);number("cleanup_failures",e.cleanupFailures);number("settings_cleanup_deferred",e.settingsCleanupDeferred);
    number("pending",e.pending);number("blocked",e.blocked);number("acknowledged_awaiting_cleanup",e.acknowledged);
    const auto& m=status.resources;
    result+=",\"resources\":{\"sampled_us\":"+std::to_string(m.sampledUs);
    number("internal_free_bytes",m.internalFree);number("internal_largest_block_bytes",m.internalLargest);
    number("internal_minimum_free_bytes",m.internalMinimum);number("psram_free_bytes",m.psramFree);
    number("psram_largest_block_bytes",m.psramLargest);number("psram_minimum_free_bytes",m.psramMinimum);
    number("worker_minimum_free_stack_bytes",m.stackMinimumBytes);result+="}";
    // Inventory is the latest scan, not a live filesystem size measurement.
    result+=",\"last_inventory\":{\"complete\":"+std::string(r.complete?"true":"false");
    number("disk_bytes",r.diskBytes);number("files",r.files);number("ready_records",r.ready);
    number("partial",r.partial);number("damaged",r.damaged);number("unexpected",r.unexpected);number("over_capacity",r.overCapacity);
    result+="},\"training_eligible\":false}";return result;
}
}
