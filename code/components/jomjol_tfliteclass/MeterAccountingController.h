#pragma once
#include "MeterAssumptionsRuntime.h"
#include "MeterAssumptionsStore.h"
namespace meter {
// All methods run under the processing owner; publish current() as a value copy.
class AccountingController {
    AssumptionsRuntime runtime;
    std::string settingsPath;
    bool attempted=false,settingsError=false;
public:
    AccountingController(const std::string& directory,const std::string& model,const std::string& calibration):
        runtime(directory,model,calibration),settingsPath(directory+"/meter-assumptions.json"){}
    bool initialize(ConfigJournal::Storage& disk){
        if(attempted)return runtime.session()!=nullptr;
        attempted=true;
        AssumptionsStore::Snapshot saved;
        if(AssumptionsStore::recoverSettings(disk,settingsPath)!=ConfigJournal::Result::Ok||
           AssumptionsStore::inspect(disk,settingsPath,saved)!=ConfigJournal::Result::Ok){
            settingsError=true;return false;
        }
        return runtime.activate(disk,saved.value);
    }
    // Call only after a verified save at a processing boundary.
    bool apply(ConfigJournal::Storage& disk,const Assumptions& value){
        attempted=true;
        const bool ok=runtime.activate(disk,value);
        if(ok)settingsError=false;
        return ok;
    }
    std::string activeNamespace()const{return runtime.activeNamespace();}
    bool active()const{return runtime.session()!=nullptr;}
    SessionResult current()const{
        const auto* session=runtime.session();
        SessionResult value=session?session->current():SessionResult();
        const auto saved=runtime.persistence();
        value.persistenceState=settingsError?"settings_unavailable":storeStatusName(saved);
        if(attempted&&!session){value.state=SessionState::Rejected;value.interval.reason=Reason::AccountingUnavailable;}
        value.referencePersisted=value.hasReference&&(saved==StoreStatus::Ready||saved==StoreStatus::RecoveredOlder||saved==StoreStatus::Saved);
        value.cumulativePersisted=value.cumulative.available&&value.referencePersisted;
        return value;
    }
    void beginIfUsed(){auto* s=runtime.session();if(s&&s->current().observed)s->begin();}
    void reject(ConfigJournal::Storage& disk,Reason reason){if(initialize(disk))runtime.session()->reject(reason);}
    void observe(ConfigJournal::Storage& disk,const Frame& frame){
        if(!initialize(disk))return;
        runtime.session()->observe(frame);
        const auto state=runtime.session()->current().state;
        if(state==SessionState::Baseline||state==SessionState::Restarted||state==SessionState::Interval)runtime.save(disk);
    }
};
}
