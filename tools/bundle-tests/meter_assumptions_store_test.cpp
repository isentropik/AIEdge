#include "MeterAssumptionsStore.h"
#include <map>
#include <cassert>
struct Disk:ConfigJournal::Storage {
 std::map<std::string,std::string> files;
 int writes=0,failAt=0;bool failRemove=false,readError=false;
 ConfigJournal::Read read(const std::string& p,std::string& b)override {
  if(readError)return ConfigJournal::Read::Error;
  auto i=files.find(p);if(i==files.end())return ConfigJournal::Read::Missing;
  b=i->second;return ConfigJournal::Read::Ok;
 }
 bool writeSync(const std::string& p,const std::string& b)override {
  ++writes;if(writes==failAt){files[p]=b.substr(0,b.size()/2);return false;}
  files[p]=b;return true;
 }
 bool remove(const std::string& p)override {
  if(failRemove)return false;return files.erase(p)==1;
 }
};
int main(){using namespace meter::AssumptionsStore;
 const std::string off=R"({"version":1,"maximum_flow_ft3_hour":null})";
 const std::string on=R"({"version":1,"maximum_flow_ft3_hour":360})";
 const std::string other=R"({"version":1,"maximum_flow_ft3_hour":720})";
 Disk d;assert(commit(d,"flow",false,"",off)==Result::Ok);
 assert(commit(d,"flow",true,off,on)==Result::Ok);
 assert(d.files["flow"]==on&&!d.files.count("flow.journal"));
 auto count=d.writes;
 assert(commit(d,"flow",true,off,other)==Result::Conflict&&d.writes==count);
 assert(commit(d,"flow",true,on,on)==Result::Ok&&d.writes==count);
 assert(commit(d,"flow",true,on,"bad")==Result::Conflict&&d.writes==count);
 assert(commit(d,"flow",true,on,off)==Result::Ok&&d.files["flow"]==off);
 // Interruption before journal completion leaves the prior setting and evidence.
 Disk journal;journal.files["flow"]=off;journal.failAt=1;
 assert(commit(journal,"flow",true,off,on)==Result::IoError);
 assert(journal.files["flow"]==off);
 assert(recoverSettings(journal,"flow")==Result::InvalidJournal);
 // Torn settings write restores the old document (including initially absent).
 for(bool existed:{false,true}) {
  Disk torn;if(existed)torn.files["flow"]=off;torn.failAt=2;
  assert(commit(torn,"flow",existed,existed?off:"",on)==Result::IoError);
  assert(!torn.files.count("flow.journal"));
  assert(existed?torn.files["flow"]==off:!torn.files.count("flow"));
 }
 // Model power loss at each durable transaction boundary, then restart recovery.
 for(bool existed:{false,true})for(int stage=0;stage<4;++stage){
  Disk reboot;reboot.files["flow.journal"]=ConfigJournal::encode(existed?"1"+off:"0",on);
  if(stage==0&&existed)reboot.files["flow"]=off;
  if(stage==1)reboot.files["flow"]="torn";
  if(stage==2)reboot.files["flow"]=on;
  if(stage==3)reboot.files["flow"]=other;
  assert(recoverSettings(reboot,"flow")== (stage==3?Result::Conflict:Result::Ok));
  if(stage==3){assert(reboot.files["flow"]==other&&reboot.files.count("flow.journal"));continue;}
  assert(!reboot.files.count("flow.journal"));
  if(stage==2)assert(reboot.files["flow"]==on);
  else assert(existed?reboot.files["flow"]==off:!reboot.files.count("flow"));
 }
 Disk cleanup;cleanup.failRemove=true;
 assert(commit(cleanup,"flow",false,"",on)==Result::CleanupPending);
 assert(cleanup.files["flow"]==on);
 assert(commit(cleanup,"flow",true,on,off)==Result::IoError);
 cleanup.failRemove=false;assert(recoverSettings(cleanup,"flow")==Result::Ok);
 assert(cleanup.files["flow"]==on&&!cleanup.files.count("flow.journal"));
 Disk io;io.readError=true;assert(commit(io,"flow",false,"",on)==Result::IoError&&io.writes==0);
 Snapshot snapshot;Disk fresh;
 assert(inspect(fresh,"flow",snapshot)==Result::Ok&&!snapshot.existed&&!snapshot.value.hasMaximumFlow);
 fresh.files["flow"]=on;
 assert(inspect(fresh,"flow",snapshot)==Result::Ok&&snapshot.existed&&snapshot.value.maximumFlowFt3Hour==360);
 for(const auto& corrupt:{std::string(""),std::string("bad"),std::string("null")}) {
  fresh.files["flow"]=corrupt;
  assert(inspect(fresh,"flow",snapshot)==Result::Conflict&&snapshot.bytes==on);
 }
 fresh.files["flow"]=off;fresh.files["flow.journal"]=ConfigJournal::encode("1"+on,off);
 const auto beforeFiles=fresh.files;
 assert(inspect(fresh,"flow",snapshot)==Result::Conflict&&fresh.files==beforeFiles&&fresh.writes==0);
 assert(recoverSettings(fresh,"flow")==Result::Ok);
 assert(inspect(fresh,"flow",snapshot)==Result::Ok&&!snapshot.value.hasMaximumFlow);

}
