#pragma once
#include "ImageArchiveEngine.h"
namespace ImageArchive {
struct ResourceStatus {
    uint64_t sampledUs=0;
    uint32_t internalFree=0,internalLargest=0,internalMinimum=0;
    uint32_t psramFree=0,psramLargest=0,psramMinimum=0,stackMinimumBytes=0;
};
struct WorkerStatus {
    bool started=false;
    uint32_t handedOff=0, dropped=0;
    EngineStatus engine;
    ResourceStatus resources;
};
// Startup-only configuration. Does not enable itself or create a destination.
bool startArchiveWorker(const std::string& root,const Destination& destination);
// Copies into one bounded PSRAM slot; never waits for disk/network. A true return
// means handed off, not durably saved. Snapshot reports subsequent failures.
bool submitArchiveImage(const CaptureMetadata& metadata,const unsigned char* image,size_t length,const std::string& settings);
WorkerStatus archiveWorkerStatus();
}
