
#include "ImageArchiveWorker.h"
#include "ImageArchiveSha.h"
#include <cassert>
#include <cstdlib>
#include <iostream>
#include <thread>
using namespace ImageArchive;
int mode=0,allocations=0,frees=0,deletedQueues=0;void* pending=nullptr;void* taskArg=nullptr;void(*task)(void*)=nullptr;
CaptureMetadata metadata;std::string image="saved capture",settings="capture-settings-v1\nsource=worker\n";
void* xQueueCreate(int n,size_t size){assert(n==1&&size==sizeof(void*));return mode==1?nullptr:reinterpret_cast<void*>(1);}
void vQueueDelete(void*){++deletedQueues;}
int xTaskCreate(void(*fn)(void*),const char*,int stack,void* arg,int priority,void*){
    assert(stack>=16384&&priority==1);task=fn;taskArg=arg;return mode==2?0:1;
}
int xQueueSend(void*,void* item,int wait){assert(wait==0);if(mode==4)return 0;assert(!pending);pending=*static_cast<void**>(item);return 1;}
int xQueueReceive(void*,void* item,int){
    assert(archiveWorkerStatus().engine.ready);
    bool accepted=submitArchiveImage(metadata,reinterpret_cast<const unsigned char*>(image.data()),image.size(),settings);
    if(mode==3||mode==4){assert(!accepted);return 0;}
    assert(accepted);assert(!submitArchiveImage(metadata,reinterpret_cast<const unsigned char*>(image.data()),image.size(),settings));
    *static_cast<void**>(item)=pending;pending=nullptr;return 1;
}
struct Stop{};void vTaskDelay(int){throw Stop{};}
void* heap_caps_malloc(size_t size,int flags){assert(flags==3);++allocations;return mode==3?nullptr:std::malloc(size);}
void heap_caps_free(void* ptr){++frees;std::free(ptr);}
int64_t esp_timer_get_time(){return 1000000;}
namespace ImageArchive {
UploadAttempt uploadSpool(const std::string& root,const Ticket& ticket){return UploadAttempt{};}
UploadAttempt uploadSpool(const std::string& root,const Ticket& ticket,const Destination&){
    assert(allocations==frees); // No copied image remains during network work.
    const int before=allocations;
    if(mode==10) {
        // The upload callback is still active while another task attempts capture
        // admission. No disk/network callback or extra PSRAM slot is allowed.
        const auto dropsBefore=archiveWorkerStatus().dropped;
        std::thread producer([&](){
            for(int i=0;i<32;++i) {
                assert(!submitArchiveImage(metadata,
                    reinterpret_cast<const unsigned char*>(image.data()),image.size(),settings));
            }
        });
        producer.join();
        assert(archiveWorkerStatus().dropped==dropsBefore+32);
        assert(allocations==before && allocations==frees && pending==nullptr);
    }
    assert(!submitArchiveImage(metadata,reinterpret_cast<const unsigned char*>(image.data()),image.size(),settings));
    assert(allocations==before); // Refused before allocating another PSRAM image.
    CaptureMetadata m;UploadRecord r;assert(readSpoolFile<Sha256>(root+"/"+ticket.identity.capture+".spool",m,r)==SpoolResult::Saved);
    assert(r.identity==ticket.identity);std::string savedSettings;assert(readSettingsFile<Sha256>(root,m.settingsHash,savedSettings)==SpoolResult::Saved && savedSettings==settings);UploadAttempt a;a.status=201;a.error=nullptr;
    a.receipt.version=1;a.receipt.capture=r.identity.capture;a.receipt.image=r.identity.image;a.receipt.record=r.identity.record;
    a.receipt.verifiedReadback=true;a.receipt.trainingEligible=false;a.receipt.reviewStatus="unreviewed";
    if(mode==5){a.status=0;a.error="connection_failed";a.receipt=Receipt{};}
    if(mode==6){a.status=401;a.error="server_rejected";a.receipt=Receipt{};}
    if(mode==7){a.receipt.image=std::string(64,'0');a.error="receipt_invalid";}
    if(mode==8){a.status=503;a.error="server_rejected";a.receipt=Receipt{};}
    if(mode==9){a.status=429;a.error="server_rejected";a.receipt=Receipt{};}
    return a;
}
}
int main(int argc,char** argv){
    assert(argc==3);mode=std::atoi(argv[2]);Destination d;d.host="storage";d.token=std::string(32,'a');d.certificatePem="test trust anchor";
    metadata.device="meter";metadata.boot="boot";metadata.imageBytes=image.size();metadata.imageHash=hashBytes<Sha256>(image);
    metadata.firmwareHash=std::string(64,'1');metadata.modelHash=std::string(64,'2');metadata.calibrationHash=std::string(64,'3');metadata.settingsHash=hashBytes<Sha256>(settings);
    assert(!submitArchiveImage(metadata,reinterpret_cast<const unsigned char*>(image.data()),image.size(),settings));
    bool started=startArchiveWorker(argv[1],d);
    if(mode==1||mode==2){assert(!started);assert(!archiveWorkerStatus().started);assert(deletedQueues==(mode==2?1:0));return 0;}
    assert(started);assert(!startArchiveWorker(argv[1],d));
    try{task(taskArg);assert(false);}catch(Stop&){}
    auto status=archiveWorkerStatus();assert(status.engine.ready);
    assert(status.resources.sampledUs==1000000&&status.resources.stackMinimumBytes==1024);
    assert(status.resources.internalFree==600&&status.resources.psramLargest==240&&status.resources.psramMinimum==180);
    if(mode==0||mode==10){assert(status.handedOff==1&&status.engine.uploaded==1&&status.engine.pending==0);assert(allocations==1&&frees==1);}
    else if(mode>=5){
        assert(status.handedOff==1&&status.engine.uploaded==0&&status.engine.failures==1);
        const bool blocked=mode==6||mode==7;
        assert(status.engine.blocked==(blocked?1:0)&&status.engine.pending==(blocked?0:1));
        assert(allocations==1&&frees==1);
        UploadRecord expected;assert(buildRecord(metadata,hashBytes<Sha256>,expected));
        CaptureMetadata persisted;UploadRecord record;
        assert(readSpoolFile<Sha256>(std::string(argv[1])+"/"+expected.identity.capture+".spool",persisted,record)==SpoolResult::Saved);
        assert(record.identity==expected.identity);
        std::string persistedSettings;assert(readSettingsFile<Sha256>(argv[1],metadata.settingsHash,persistedSettings)==SpoolResult::Saved);
        assert(persistedSettings==settings); // Neither image nor settings removed on failure.
    }
    else {assert(status.handedOff==0&&status.engine.uploaded==0);assert(frees==(mode==4?1:0));}
    assert(pending==nullptr);std::cout<<"Worker scenario "<<mode<<" passed\n";
}
