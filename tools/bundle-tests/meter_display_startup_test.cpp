#include "MeterDisplayStartup.h"
#include <map>
#include <cassert>
#include <iostream>
struct Disk:ConfigJournal::Storage{
 std::map<std::string,std::string> files;int reads=0,writes=0;bool failRead=false,failRemove=false;
 ConfigJournal::Read read(const std::string&p,std::string&b)override{++reads;if(failRead)return ConfigJournal::Read::Error;auto i=files.find(p);if(i==files.end())return ConfigJournal::Read::Missing;b=i->second;return ConfigJournal::Read::Ok;}
 bool writeSync(const std::string&p,const std::string&b)override{++writes;files[p]=b;return true;}
 bool remove(const std::string&p)override{if(failRemove)return false;return files.erase(p)==1;}
};
int main(){using namespace meter;
 const std::string ft3=R"({"version":1,"kind":"gas","source_unit":"ft3","display_unit":"ft3","units_per_count":1,"has_secondary":true,"secondary_units_per_revolution":5,"confirmed":true})";
 auto m3=ft3;m3.replace(m3.find("\"display_unit\":\"ft3\""),20,"\"display_unit\":\"m3\"");
 RegisterProfile profile;assert(parseProfile(m3,profile));
 Disk d;d.files["p"]=m3;auto original=d.files;
 assert(!restoreDisplayProfile(d,"p")&&activeDisplayUnit()==RegisterUnit::CubicMetre);assert(d.files==original&&d.writes==0);
 auto reads=d.reads;assert(restoreDisplayProfile(d,"p",false));assert(activeDisplayUnit()==RegisterUnit::Unknown&&d.reads==reads&&d.files==original);
 d.files.clear();assert(!restoreDisplayProfile(d,"p")&&activeDisplayUnit()==RegisterUnit::Unknown);
 d.files["p"]=ft3;assert(!restoreDisplayProfile(d,"p")&&activeDisplayUnit()==RegisterUnit::CubicFoot);
 d.files["p"]="bad";assert(restoreDisplayProfile(d,"p")&&activeDisplayUnit()==RegisterUnit::Unknown&&d.files["p"]=="bad");
 d.files["p"]=ft3;d.failRead=true;assert(restoreDisplayProfile(d,"p")&&activeDisplayUnit()==RegisterUnit::Unknown);d.failRead=false;
 d.files["p.journal"]="corrupt";original=d.files;assert(restoreDisplayProfile(d,"p")&&d.files==original&&activeDisplayUnit()==RegisterUnit::Unknown);
 d.files["p.journal"]=ConfigJournal::encode("1"+ft3,m3);d.files["p"]="torn";assert(!restoreDisplayProfile(d,"p")&&d.files["p"]==ft3&&activeDisplayUnit()==RegisterUnit::CubicFoot);
 d.files["p.journal"]=ConfigJournal::encode("1"+ft3,m3);d.files["p"]=m3;d.failRemove=true;assert(!restoreDisplayProfile(d,"p")&&activeDisplayUnit()==RegisterUnit::CubicMetre&&d.files.count("p.journal"));
 d.failRemove=false;d.files.erase("p.journal");auto incompatible=ft3;auto at=incompatible.find("\"units_per_count\":1");incompatible.replace(at,19,"\"units_per_count\":2");d.files["p"]=incompatible;assert(!restoreDisplayProfile(d,"p")&&activeDisplayUnit()==RegisterUnit::Unknown);
 std::cout<<"Profile startup: valid/missing/incompatible, storage gate, read failure, corrupt/torn journal, cleanup pending, preserved data passed\n";
}
