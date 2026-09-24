#include "MeterProfileStore.h"
#include <map>
#include <cassert>
#include <cstdio>
struct Disk:ConfigJournal::Storage {
 std::map<std::string,std::string> files;int writes=0,failAt=0;bool failRemove=false;
 ConfigJournal::Read read(const std::string&p,std::string&b)override{auto i=files.find(p);if(i==files.end())return ConfigJournal::Read::Missing;b=i->second;return ConfigJournal::Read::Ok;}
 bool writeSync(const std::string&p,const std::string&b)override{++writes;if(writes==failAt){files[p]=b.substr(0,b.size()/2);return false;}files[p]=b;return true;}
 bool remove(const std::string&p)override{if(failRemove)return false;return files.erase(p)==1;}
};
std::string change(std::string s,const std::string&a,const std::string&b){auto p=s.find(a);assert(p!=std::string::npos);return s.replace(p,a.size(),b);}
int main(){using namespace meter;using namespace ProfileStore;
 const std::string base=R"({"version":1,"kind":"gas","source_unit":"ft3","display_unit":"ft3","units_per_count":1,"has_secondary":true,"secondary_units_per_revolution":5,"confirmed":true})";
 RegisterProfile p;assert(parseProfile(base,p));
 const std::string display=change(base,"\"display_unit\":\"ft3\"","\"display_unit\":\"m3\"");
 for(const auto&bad:{change(base,"\"version\":1","\"version\":2"),change(base,"\"confirmed\":true","\"confirmed\":1"),change(base,"\"kind\":\"gas\"","\"kind\":\"gas\\u0000bad\""),change(base,"\"kind\":\"gas\"","\"kind\":\"gas\",\"kind\":\"water\""),change(base,"\"units_per_count\":1","\"units_per_count\":1e999"),change(base,"\"confirmed\":true","\"extra\":true"),base+"trailing",change(base,"\"source_unit\":\"ft3\"","\"source_unit\":\"kWh\"")}){
  RegisterProfile untouched;p.unitsPerRegisterCount=42;assert(!parseProfile(bad,p));assert(p.unitsPerRegisterCount==42);
 }
 Disk disk;assert(commit(disk,"p",false,"",base)==Result::Ok);assert(disk.files["p"]==base&&!disk.files.count("p.journal"));
 assert(commit(disk,"p",true,base,display)==Result::Ok);assert(disk.files["p"]==display);
 int before=disk.writes;assert(commit(disk,"p",true,base,display)==Result::Conflict);assert(disk.writes==before);
 auto scale=change(display,"\"units_per_count\":1","\"units_per_count\":100");assert(commit(disk,"p",true,display,scale)==Result::Conflict);assert(disk.writes==before);
 disk.files["p.journal"]=ConfigJournal::encode("1"+base,display);disk.files["p"]="torn";assert(recoverSettings(disk,"p")==Result::Ok);assert(disk.files["p"]==base);
 Disk missing;missing.files["p.journal"]=ConfigJournal::encode("0",base);missing.files["p"]="torn";assert(recoverSettings(missing,"p")==Result::Ok);assert(missing.files.empty());
 Disk failed;failed.failAt=2;assert(commit(failed,"p",false,"",base)==Result::IoError);assert(failed.files.empty());
 Disk corrupt;corrupt.files["p.journal"]="bad";assert(recoverSettings(corrupt,"p")==Result::InvalidJournal);assert(corrupt.files["p.journal"]=="bad");
 Disk conflict;conflict.files["p.journal"]=ConfigJournal::encode("1"+base,display);conflict.files["p"]=scale;assert(recoverSettings(conflict,"p")==Result::Conflict);assert(conflict.files["p"]==scale);
 puts("Strict profile parsing, first save, display change, scale/stale conflicts and interrupted-save recovery passed");
}
