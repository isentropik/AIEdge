#pragma once
#include "MeterSession.h"
#include "MeterRecovery.h"
#include "FileConfigStorage.h"
#include "PolarIdentity.h"
#include "freertos/FreeRTOS.h"
#include "esp_random.h"

namespace PolarAccounting {
// Called only by the processing owner; readers receive a locked value copy.
inline meter::Session& session() { static meter::Session value;return value; }
inline meter::Recovery& recovery() {
    static meter::Recovery value("/sdcard/config/polar-meter-reference",polar::modelIdentity,polar::geometryIdentity);
    return value;
}
inline void initialize() {
    ConfigStorage::Files files;recovery().initialize(files,session());
}
inline meter::SessionResult& published() {static meter::SessionResult value;return value;}
inline portMUX_TYPE& mutex() {static portMUX_TYPE value=portMUX_INITIALIZER_UNLOCKED;return value;}
inline void publish() {
    auto value=session().current();
    const auto saved=recovery().current();
    value.persistenceState=meter::storeStatusName(saved);
    value.referencePersisted=value.hasReference && (saved==meter::StoreStatus::Ready ||
        saved==meter::StoreStatus::RecoveredOlder || saved==meter::StoreStatus::Saved);
    value.cumulativePersisted=value.cumulative.available&&value.referencePersisted;
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
inline void reject() {initialize();session().reject(meter::Reason::MainUnknown);publish();}
inline void beginIfUsed() {
    if (session().current().observed) {session().begin();publish();}
}
inline void observe(const float* readings,int64_t captureUs,bool valid) {
    initialize();
    meter::Frame frame{};
    for(int i=0;i<5;++i)frame.main[i]=readings[i];
    frame.secondary=readings[5];frame.captureUs=captureUs;
    frame.captureTimeValid=valid;frame.clockId=bootIdentity();
    session().observe(frame);
    const auto state=session().current().state;
    if (state==meter::SessionState::Baseline || state==meter::SessionState::Restarted || state==meter::SessionState::Interval) {
        ConfigStorage::Files files;recovery().save(files,session());
    }
    publish();
}
}
