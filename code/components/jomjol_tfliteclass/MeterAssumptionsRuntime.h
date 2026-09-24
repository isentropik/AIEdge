#pragma once
#include "MeterAssumptions.h"
#include "MeterRecovery.h"
#include <memory>
namespace meter {
// Single processing owner only. HTTP callers must hold the processing guard.
// A failed transition leaves the old session active and reports failure; the
// caller must keep saved-versus-active state visible instead of claiming success.
class AssumptionsRuntime {
    struct Active {
        std::string name;
        Session session;
        Recovery recovery;
        Active(const std::string& directory,const std::string& n,
               const std::string& model,const std::string& calibration,const Bounds& b):
            name(n),session(b),recovery(directory+"/"+n,model,calibration,b){}
    };
    std::string directory,model,calibration;
    std::unique_ptr<Active> active;
    StoreStatus lastStatus=StoreStatus::Empty;
    static bool usable(StoreStatus status) {
        return status==StoreStatus::Empty||status==StoreStatus::Ready||
            status==StoreStatus::RecoveredOlder||status==StoreStatus::Saved;
    }
public:
    AssumptionsRuntime(std::string d,std::string m,std::string c):
        directory(d),model(m),calibration(c){}
    Session* session(){return active?&active->session:nullptr;}
    const Session* session()const{return active?&active->session:nullptr;}
    const std::string activeNamespace()const{return active?active->name:std::string();}
    StoreStatus status()const{return lastStatus;}
    StoreStatus persistence()const{return active?active->recovery.current():lastStatus;}
    bool activate(ConfigJournal::Storage& disk,const Assumptions& assumptions){
        Bounds bounds;std::string name;
        if(!assumptionBounds(assumptions,bounds)||!assumptionNamespace(assumptions,name)){
            lastStatus=StoreStatus::Conflict;return false;
        }
        // No-op edits must not reset the reference or discard accumulated turns.
        if(active&&active->name==name){lastStatus=active->recovery.current();return usable(lastStatus);}
        std::unique_ptr<Active> next(new Active(directory,name,model,calibration,bounds));
        lastStatus=next->recovery.initialize(disk,next->session);
        if(!usable(lastStatus))return false;
        // Preserve the outgoing reference before losing its in-memory segment.
        // Never blindly retry a previous uncertain checkpoint write.
        if(active){
            lastStatus=active->recovery.save(disk,active->session);
            if(!usable(lastStatus))return false;
        }
        active.swap(next);lastStatus=active->recovery.current();return true;
    }
    StoreStatus save(ConfigJournal::Storage& disk){
        if(!active){lastStatus=StoreStatus::Conflict;return lastStatus;}
        lastStatus=active->recovery.save(disk,active->session);return lastStatus;
    }
};
}
