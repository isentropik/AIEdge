#include "MeterAccountingController.h"
#include <map>
#include <cassert>
struct Disk:ConfigJournal::Storage {
 std::map<std::string,std::string> files;bool failWrites=false;
 ConfigJournal::Read read(const std::string&p,std::string&b)override{auto i=files.find(p);if(i==files.end())return ConfigJournal::Read::Missing;b=i->second;return ConfigJournal::Read::Ok;}
 bool writeSync(const std::string&p,const std::string&b)override{if(failWrites)return false;files[p]=b;return true;}
 bool remove(const std::string&p)override{return files.erase(p)==1;}
};
meter::Frame frame(double total,int64_t time){
 meter::Frame f{};double divisor=1000000;
 for(int i=0;i<5;++i,divisor/=10)f.main[i]=std::fmod(total/divisor,10);
 f.secondary=std::fmod(2*(total-1000)+1+10000,10);
 f.captureUs=time;f.captureTimeValid=true;f.clockId=1;return f;
}
int main(){using namespace meter;
 Disk disk;Assumptions off,on;on.hasMaximumFlow=true;on.maximumFlowFt3Hour=360;
 AssumptionsRuntime runtime("config",std::string(64,'a'),std::string(64,'b'));
 assert(!runtime.session());assert(runtime.activate(disk,on));
 const auto enabled=runtime.activeNamespace();
 runtime.session()->observe(frame(1000,1000000));
 runtime.session()->observe(frame(1002,31000000));
 assert(runtime.session()->current().cumulative.estimatedFt3==2);
 assert(runtime.save(disk)==StoreStatus::Saved);
 auto* old=runtime.session();
 assert(runtime.activate(disk,on)&&runtime.session()==old);
 assert(runtime.session()->current().cumulative.estimatedFt3==2);
 Assumptions bad=on;bad.maximumFlowFt3Hour=-1;
 assert(!runtime.activate(disk,bad)&&runtime.session()==old);
 // Bad target cannot replace the working runtime or overwrite evidence.
 disk.files["config/polar-meter-reference.0"]="broken";
 const auto evidence=disk.files;
 assert(!runtime.activate(disk,off)&&runtime.session()==old&&disk.files==evidence);
 disk.files.erase("config/polar-meter-reference.0");
 assert(runtime.activate(disk,off)&&!runtime.session()->current().hasReference);
 assert(runtime.activeNamespace()!=enabled);
 runtime.session()->observe(frame(1004,61000000));
 assert(runtime.session()->current().state==SessionState::Baseline);
 assert(runtime.session()->current().cumulative.minimumFt3==0);
 assert(runtime.save(disk)==StoreStatus::Saved);
 // Returning to old settings restores evidence, but never bridges the gap.
 assert(runtime.activate(disk,on)&&runtime.activeNamespace()==enabled);
 assert(runtime.session()->current().state==SessionState::Restarted);
 runtime.session()->observe(frame(1006,91000000));
 assert(runtime.session()->current().hasRestartGap);
 assert(runtime.session()->current().cumulative.minimumFt3==0);
 assert(runtime.session()->current().cumulative.anchorUs==91000000);
 assert(runtime.save(disk)==StoreStatus::Saved);
 bool segment=false;for(const auto& file:disk.files)if(file.first.find(enabled+".segment-")!=std::string::npos)segment=true;
 assert(segment);
 // Failed outgoing persistence keeps the current session and inhibits retries.
 old=runtime.session();disk.failWrites=true;
 assert(!runtime.activate(disk,off)&&runtime.session()==old);
 disk.failWrites=false;const auto afterFailure=disk.files;
 assert(!runtime.activate(disk,off)&&runtime.session()==old&&disk.files==afterFailure);
 // Real processing controller: missing settings stay disabled, saved settings
 // activate on startup, and damage must not fall back to unrestricted tracking.
 Disk empty;AccountingController defaults("d",std::string(64,'a'),std::string(64,'b'));
 defaults.observe(empty,frame(1000,1000000));
 assert(defaults.active()&&!defaults.current().assumptions.hasMaximumRate);
 assert(defaults.current().referencePersisted);
 Disk configured;configured.files["d/meter-assumptions.json"]=R"({"version":1,"maximum_flow_ft3_hour":360})";
 AccountingController controlled("d",std::string(64,'a'),std::string(64,'b'));
 controlled.observe(configured,frame(1000,1000000));controlled.observe(configured,frame(1002,31000000));
 assert(controlled.current().cumulative.estimatedFt3==2&&controlled.current().cumulativePersisted);
 controlled.beginIfUsed();assert(controlled.current().state==SessionState::Pending&&!controlled.current().cumulative.current);
 AccountingController reboot("d",std::string(64,'a'),std::string(64,'b'));
 reboot.observe(configured,frame(1004,61000000));assert(reboot.current().hasRestartGap);
 Disk damaged;damaged.files["d/meter-assumptions.json"]="broken";
 AccountingController blocked("d",std::string(64,'a'),std::string(64,'b'));
 blocked.observe(damaged,frame(1000,1000000));assert(!blocked.active());
 assert(blocked.current().state==SessionState::Rejected&&blocked.current().interval.reason==Reason::InvalidBounds);
 assert(std::string(blocked.current().persistenceState)=="settings_unavailable");
 damaged.files["d/meter-assumptions.json"]=R"({"version":1,"maximum_flow_ft3_hour":360})";
 blocked.observe(damaged,frame(1002,31000000));assert(!blocked.active()); // no blind retry
 assert(blocked.apply(damaged,on));blocked.observe(damaged,frame(1004,61000000));
 assert(blocked.current().state==SessionState::Baseline);

}
