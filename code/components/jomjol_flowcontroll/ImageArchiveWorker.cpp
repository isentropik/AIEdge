#include "ImageArchiveWorker.h"
#include "ImageArchiveSha.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include <atomic>
#include <cstring>
#include <new>

namespace ImageArchive {
namespace {
struct Job {CaptureMetadata metadata;std::string settings;unsigned char* bytes=nullptr;size_t length=0;};
struct Context {std::string root;Destination destination;QueueHandle_t inbox=nullptr;ArchiveEngine<Sha256> engine;};
Context* context=nullptr;
std::atomic<bool> starting{false},active{false};
std::atomic_flag reserved=ATOMIC_FLAG_INIT;
std::atomic<uint32_t> handedOff{0},dropped{0};
portMUX_TYPE snapshotMux=portMUX_INITIALIZER_UNLOCKED;
EngineStatus snapshot;
ResourceStatus resourceSnapshot;
void publish(Context* c) {
    const auto next=c->engine.status();
    ResourceStatus memory;
    memory.sampledUs=static_cast<uint64_t>(esp_timer_get_time());
    const uint32_t internal=MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT,external=MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT;
    memory.internalFree=heap_caps_get_free_size(internal);
    memory.internalLargest=heap_caps_get_largest_free_block(internal);
    memory.internalMinimum=heap_caps_get_minimum_free_size(internal);
    memory.psramFree=heap_caps_get_free_size(external);
    memory.psramLargest=heap_caps_get_largest_free_block(external);
    memory.psramMinimum=heap_caps_get_minimum_free_size(external);
    memory.stackMinimumBytes=uxTaskGetStackHighWaterMark(nullptr)*sizeof(StackType_t);
    portENTER_CRITICAL(&snapshotMux);snapshot=next;resourceSnapshot=memory;portEXIT_CRITICAL(&snapshotMux);
}
void run(void* arg) {
    auto* c=static_cast<Context*>(arg);
    c->engine.start(c->root);publish(c);
    for(;;) {
        Job* job=nullptr;
        if(xQueueReceive(c->inbox,&job,pdMS_TO_TICKS(1000))==pdTRUE) {
            c->engine.enqueue(job->metadata,job->bytes,job->length,job->settings);
            heap_caps_free(job->bytes);delete job;
            // Keep admission reserved after releasing image RAM: an HTTPS
            // request must not retain a second capture buffer behind it.
            publish(c);
        } else if(reserved.test_and_set(std::memory_order_acquire)) {
            // A producer owns or just queued a job. Drain it before networking.
            continue;
        }
        c->engine.step([](){return static_cast<uint64_t>(esp_timer_get_time()/1000);},
            [&](const std::string& root,const Ticket& ticket){return uploadSpool(root,ticket,c->destination);});
        reserved.clear(std::memory_order_release);
        publish(c);
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
}
bool startArchiveWorker(const std::string& root,const Destination& destination) {
    if(root.empty() || !validArchiveDestination(destination))return false;
    if(starting.exchange(true,std::memory_order_acq_rel))return false;
    auto* c=new(std::nothrow) Context;
    if(!c){starting.store(false,std::memory_order_release);return false;}
    c->root=root;c->destination=destination;c->inbox=xQueueCreate(1,sizeof(Job*));
    if(!c->inbox){delete c;starting.store(false,std::memory_order_release);return false;}
    // Separate low-priority worker; actual high-water mark must be measured.
    if(xTaskCreate(run,"image_archive",24576,c,1,nullptr)!=pdPASS) {
        vQueueDelete(c->inbox);delete c;starting.store(false,std::memory_order_release);return false;
    }
    context=c;active.store(true,std::memory_order_release);return true;
}
WorkerStatus archiveWorkerStatus() {
    WorkerStatus result;result.started=active.load(std::memory_order_acquire);
    result.handedOff=handedOff.load();result.dropped=dropped.load();
    portENTER_CRITICAL(&snapshotMux);result.engine=snapshot;result.resources=resourceSnapshot;portEXIT_CRITICAL(&snapshotMux);
    return result;
}
bool submitArchiveImage(const CaptureMetadata& metadata,const unsigned char* image,size_t length,const std::string& settings) {
    if(!active.load(std::memory_order_acquire) || !archiveWorkerStatus().engine.ready ||
       !image || length!=metadata.imageBytes || !validMetadata(metadata) || settings.empty() || settings.size()>MaxSettingsBytes) {++dropped;return false;}
    if(reserved.test_and_set(std::memory_order_acquire)){++dropped;return false;}
    auto* job=new(std::nothrow) Job;
    if(job)job->bytes=static_cast<unsigned char*>(heap_caps_malloc(length,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
    if(!job || !job->bytes) {
        delete job;reserved.clear(std::memory_order_release);++dropped;return false;
    }
    job->metadata=metadata;job->settings=settings;job->length=length;std::memcpy(job->bytes,image,length);
    if(xQueueSend(context->inbox,&job,0)!=pdTRUE) {
        heap_caps_free(job->bytes);delete job;reserved.clear(std::memory_order_release);++dropped;return false;
    }
    ++handedOff;return true;
}
}
