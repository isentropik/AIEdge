#pragma once
#include <cstdint>
namespace MeterOtaHealth {
struct Evidence {
 bool rollbackConfigured=false,pendingImage=false,bundleVerified=false;
 bool configurationReadable=false,modelSelfTestPassed=false,processingActive=false;
 bool lastPipelineCompleted=false,lastReaderAccepted=false;
 uint32_t systemFaults=0;uint64_t consecutiveReaderCycles=0;
 int64_t nowUs=0,startedUs=0,capturedUs=0,finishedUs=0;
};
// This policy evaluates software evidence, not physical accuracy or successful
// recovery. Three completed accepted-reader cycles and a recent final capture
// are required. It performs no image acceptance, rollback or reboot itself.
inline const char* evaluate(const Evidence& e){
 if(!e.rollbackConfigured)return "rollback_not_configured";
 if(!e.pendingImage)return "image_not_pending";
 if(!e.bundleVerified)return "bundle_unverified";
 if(e.systemFaults)return "system_faults_present";
 if(!e.configurationReadable)return "configuration_unreadable";
 if(!e.modelSelfTestPassed)return "model_self_test_required";
 if(e.processingActive)return "processing_active";
 if(e.consecutiveReaderCycles<3||!e.lastPipelineCompleted||!e.lastReaderAccepted)return "successful_cycles_required";
 if(e.startedUs<=0||e.capturedUs<e.startedUs||e.finishedUs<e.capturedUs||e.nowUs<e.finishedUs)return "capture_timing_invalid";
 if(e.nowUs-e.capturedUs>180000000)return "capture_stale";
 return "ready";
}
}
