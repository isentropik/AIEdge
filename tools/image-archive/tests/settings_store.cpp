
#include "ImageArchiveSettingsStore.h"
#include <cassert>
#include <map>
#include <stdexcept>
#include <iostream>
using namespace ImageArchive::SettingsStore;
struct Disk:Storage{
 std::map<std::string,std::string> files;
 int steps=0,crash=0,writeCount=0,torn=0;bool noRemove=false;
 void tick(){if(++steps==crash)throw std::runtime_error("power loss");}
 Read read(const std::string& p,std::string& bytes)override{tick();auto it=files.find(p);if(it==files.end())return Read::Missing;bytes=it->second;return Read::Ok;}
 bool writeSync(const std::string& p,const std::string& bytes)override{tick();if(++writeCount==torn){files[p]=bytes.substr(0,bytes.size()/2);return false;}files[p]=bytes;tick();return true;}
 bool remove(const std::string& p)override{tick();if(noRemove)return false;files.erase(p);tick();return true;}
};
int main(){
 const std::string path="settings",before=R"({"version":1,"config":{"enabled":false}})",
 after=R"({"version":1,"config":{"enabled":true,"host":"server.local","device_id":"meter"},"token":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","ca_pem":"trust"})";
 assert(valid(before)&&valid(after));int cases=0;
 for(bool existed:{false,true}){
  Disk initial;if(existed)initial.files[path]=before;
  Disk clean=initial;assert(commit(clean,path,existed,existed?before:"",after)==Result::Ok);assert(clean.files[path]==after);const int steps=clean.steps;
  for(int crash=1;crash<=steps+1;++crash){
   Disk disk=initial;disk.crash=crash;
   try{commit(disk,path,existed,existed?before:"",after);}catch(const std::runtime_error&){}
   disk.crash=0;assert(recoverSettings(disk,path)==Result::Ok);
   auto it=disk.files.find(path);
   assert(existed?(it!=disk.files.end()&&(it->second==before||it->second==after)):(it==disk.files.end()||it->second==after));
   assert(!disk.files.count(path+".journal"));++cases;
  }
  for(int torn=1;torn<=2;++torn){
   Disk disk=initial;disk.torn=torn;assert(commit(disk,path,existed,existed?before:"",after)==Result::IoError);disk.torn=0;
   auto result=recoverSettings(disk,path);
   if(torn==1){assert(result==Result::InvalidJournal);assert(disk.files.count(path+".journal"));}
   else assert(result==Result::Ok);
   assert(existed?disk.files[path]==before:!disk.files.count(path));++cases;
  }
  Disk disk=initial;disk.noRemove=true;
  assert(commit(disk,path,existed,existed?before:"",after)==Result::CleanupPending);assert(disk.files[path]==after);
  assert(recoverSettings(disk,path)==Result::CleanupPending);disk.noRemove=false;assert(recoverSettings(disk,path)==Result::Ok);++cases;
 }

 for(bool existed:{false,true}){
  Disk initial;initial.files[path]=after.substr(0,20);initial.files[path+".journal"]=ConfigJournal::encode(existed?"1"+before:"0",after);
  Disk clean=initial;assert(recoverSettings(clean,path)==Result::Ok);const int steps=clean.steps;
  for(int crash=1;crash<=steps+1;++crash){
   Disk disk=initial;disk.crash=crash;
   try{recoverSettings(disk,path);}catch(const std::runtime_error&){}
   disk.crash=0;assert(recoverSettings(disk,path)==Result::Ok);
   assert(existed?disk.files[path]==before:!disk.files.count(path));assert(!disk.files.count(path+".journal"));++cases;
  }
  Disk failed=initial;
  if(existed)failed.torn=1;else failed.noRemove=true;
  assert(recoverSettings(failed,path)==Result::IoError);assert(failed.files.count(path+".journal"));
  failed.torn=0;failed.noRemove=false;assert(recoverSettings(failed,path)==Result::Ok);
  assert(existed?failed.files[path]==before:!failed.files.count(path));++cases;
 }
 Disk d;d.files[path]=before;auto unchanged=d.files;
 assert(commit(d,path,false,"",after)==Result::Conflict);assert(d.files==unchanged);
 assert(commit(d,path,true,before,"garbage")==Result::Conflict);assert(d.files==unchanged);
 const auto record=ConfigJournal::encode("1"+before,after);
 for(size_t i=0;i<record.size();++i){Disk disk;disk.files[path]=before;auto bad=record;bad[i]^=1;disk.files[path+".journal"]=bad;assert(recoverSettings(disk,path)==Result::InvalidJournal);assert(disk.files[path]==before);++cases;}
 Disk third;third.files[path]=R"({"version":1,"config":{"enabled":false,"host":"other.local"}})";third.files[path+".journal"]=record;
 assert(recoverSettings(third,path)==Result::Conflict);assert(third.files.count(path+".journal"));
 std::cout<<cases<<" crash, torn-write, cleanup and journal corruption cases passed; conflicts preserved\n";
}
