#include "ImageArchiveDestination.h"
#include "ImageArchiveEngine.h"
#include "ImageArchiveSha.h"
#include <cassert>
#include <iostream>
#ifdef _WIN32
#include <direct.h>
#else
#include <sys/stat.h>
#endif
void directory(const std::string& path){
#ifdef _WIN32
 assert(_mkdir(path.c_str())==0);
#else
 assert(mkdir(path.c_str(),0700)==0);
#endif
}
using namespace ImageArchive;
int main(int argc,char** argv){
 assert(argc==2);const std::string base=argv[1];
 Destination a;a.host="storage.local";a.token=std::string(40,'a');a.certificatePem="test-ca";
 const auto key=archiveQueueKey<Sha256>(a,"meter");assert(key.size()==64);
 assert(key.find(a.token)==std::string::npos);
 Destination b=a;
 for(int i=0;i<5;++i){b=a;std::string device="meter";
  if(i==0)b.host="other.local";if(i==1)b.port=443;if(i==2)b.token[0]='b';
  if(i==3)b.certificatePem="other-ca";if(i==4)device="other";
  assert(archiveQueueKey<Sha256>(b,device)!=key);
 }
 b=a;b.timeoutMs=2000;assert(archiveQueueKey<Sha256>(b,"meter")==key);
 assert(archiveQueueKey<Sha256>(a,"../meter").empty());b=a;b.token="short";
 assert(archiveQueueKey<Sha256>(b,"meter").empty());
 const auto first=base+"/"+key;directory(first);
 std::string image="original-camera-bytes",settings="capture-settings-v1\nsource=test\n";
 CaptureMetadata m;m.device="meter";m.boot=std::string(32,'a');m.captureUs=100;m.imageBytes=image.size();
 m.imageHash=hashBytes<Sha256>(image);m.settingsHash=hashBytes<Sha256>(settings);
 m.firmwareHash=std::string(64,'1');m.modelHash=std::string(64,'2');m.calibrationHash=std::string(64,'3');
 ArchiveEngine<Sha256> original;assert(original.start(first));
 assert(original.enqueue(m,reinterpret_cast<const unsigned char*>(image.data()),image.size(),settings)==EnqueueResult::Stored);
 // Simulated new boot: a different destination never sees the previous queue.
 b=a;b.host="other.local";const auto second=base+"/"+archiveQueueKey<Sha256>(b,"meter");directory(second);
 ArchiveEngine<Sha256> changed;assert(changed.start(second));assert(changed.status().pending==0);
 int uploads=0;changed.step([](){return uint64_t(1000);},[&](const std::string&,const Ticket&){++uploads;return UploadAttempt{};});assert(uploads==0);
 // Restore the original configuration: exactly the saved original record returns.
 ArchiveEngine<Sha256> restored;assert(restored.start(base+"/"+archiveQueueKey<Sha256>(a,"meter")));
 assert(restored.status().pending==1);
 restored.step([](){return uint64_t(1000);},[&](const std::string& root,const Ticket&){assert(root==first);++uploads;return UploadAttempt{};});assert(uploads==1);
 // Legacy unbound files are not silently adopted by a destination namespace.
 assert(writeSettingsFile<Sha256>(base,m.settingsHash,settings)==SpoolResult::Saved);
 assert(writeSpoolFile<Sha256>(base,m,reinterpret_cast<const unsigned char*>(image.data()),image.size())==SpoolResult::Saved);
 ArchiveEngine<Sha256> noLegacy;assert(noLegacy.start(second));assert(noLegacy.status().pending==0);
 std::cout<<"Destination/credential/trust/device isolation, timeout stability, restart recovery, legacy preservation and no wrong-destination upload passed\n";
}
