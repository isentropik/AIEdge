#include "PolarModelRoles.h"
#pragma once
#include "MeterAccountingController.h"
#include "FileConfigStorage.h"
#include "PolarIdentity.h"
#include "freertos/FreeRTOS.h"
#include "esp_random.h"

namespace PolarAccounting {
// Called only by the processing owner; readers receive a locked value copy.
inline meter::AccountingController& controller() {
    static meter::AccountingController value("/sdcard/config",polar::routedReaderIdentity,polar::geometryIdentity);
    return value;
}
inline meter::SessionResult& published() {static meter::SessionResult value;return value;}
inline portMUX_TYPE& mutex() {static portMUX_TYPE value=portMUX_INITIALIZER_UNLOCKED;return value;}
inline void publish() {
    const auto value=controller().current();
    portENTER_CRITICAL(&mutex());published()=value;portEXIT_CRITICAL(&mutex());
}
inline meter::SessionResult snapshot() {
    portENTER_CRITICAL(&mutex());const auto value=published();portEXIT_CRITICAL(&mutex());
    return value;
}
inline uint64_t bootIdentity() {
    static const uint64_t value=[](){
        uint64_t result=(static_cast<uint64_t>(esp_random())<<32)|esp_random();
        return result ? result : uint64_t(1);
    }();
    return value;
}
inline bool apply(const meter::Assumptions& value) {
    ConfigStorage::Files files;const bool active=controller().apply(files,value);publish();return active;
}
inline void reject() {
    ConfigStorage::Files files;controller().reject(files,meter::Reason::MainUnknown);publish();
}
inline void beginIfUsed() {controller().beginIfUsed();publish();}
inline void observe(const float* readings,int64_t captureUs,bool valid) {
    meter::Frame frame{};
    for(int i=0;i<5;++i)frame.main[i]=readings[i];
    frame.secondary=readings[5];frame.captureUs=captureUs;
    frame.captureTimeValid=valid;frame.clockId=bootIdentity();
    ConfigStorage::Files files;controller().observe(files,frame);
    publish();
}
}
