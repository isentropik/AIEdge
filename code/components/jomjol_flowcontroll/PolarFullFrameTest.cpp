#include "PolarModelRouting.h"
#include "../jomjol_controlcamera/CameraAccess.h"
#include "PolarRuntimeTest.h"
#include "ProcessingAccess.h"
#include "CTfLiteClass.h"
#include "PolarPipeline.h"
#include "../jomjol_fileserver_ota/RuntimeBundle.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mbedtls/sha256.h"
#include <memory>
#include <cstdio>
#include <cstring>
#include <algorithm>
#include <cstdlib>
#include <new>

namespace {
using File = std::unique_ptr<FILE, int(*)(FILE*)>;
bool verify(FILE* file, size_t bytes, const char* expected) {
    if (!file) return false;
    mbedtls_sha256_context context; mbedtls_sha256_init(&context);
    bool ok = mbedtls_sha256_starts(&context, 0) == 0;
    unsigned char chunk[1024], hash[32]; size_t total=0;
    while (ok && total < bytes) {
        const size_t n=std::fread(chunk,1,std::min(sizeof(chunk),bytes-total),file);
        if (!n) {ok=false;break;}
        ok=mbedtls_sha256_update(&context,chunk,n)==0;total+=n;
        if (!(total % 16384)) vTaskDelay(1);
    }
    ok=ok && total==bytes && std::fgetc(file)==EOF && !std::ferror(file);
    if(ok)ok=mbedtls_sha256_finish(&context,hash)==0;
    mbedtls_sha256_free(&context);
    char hex[65]={};if(ok)for(int i=0;i<32;++i)std::snprintf(hex+2*i,3,"%02x",hash[i]);
    return ok && std::strcmp(hex,expected)==0 && std::fseek(file,0,SEEK_SET)==0;
}
}

PolarRuntimeTestResult runPolarFullFrameTest() {
    PolarRuntimeTestResult result;
    ProcessingAccess access;
    if(!access){result.status="processing_busy";return result;}
    CameraAccess camera;
    if(!camera){result.status="camera_busy";return result;}
    // Fixed held-out RGB frame: this tests registration/features/inference, not
    // camera capture, JPEG decoding, physical accuracy or publication cadence.
    File frame(std::fopen(MeterBundle::runtimePath("/sdcard/config/polar-runtime-frame.rgb").c_str(),"rb"),std::fclose);
    File vectors(std::fopen(MeterBundle::runtimePath("/sdcard/config/polar-runtime-vectors.bin").c_str(),"rb"),std::fclose);
    constexpr size_t rgbBytes=640*480*3,inputBytes=384*40,outputBytes=360;
    if(!verify(frame.get(),rgbBytes,"a8ae2891563daff59ef44e02e87921f8b868c4e3f5c04fe283882989bbd55270") ||
       !verify(vectors.get(),8+6*(inputBytes+outputBytes),"76592a50851be4c237852ae5d6eb2e3d85f4a290fa9495ccca9c4c5c195ac175")) {
        result.status="full_frame_fixture_rejected";return result;
    }
    CTfLiteClass network;
    if(!polar::loadRole(network,polar::ModelRole::Main)) {
        result.status="model_or_allocation_rejected";return result;
    }
    // Reuse the reserved model workspace for RGB; the connected camera leaves
    // too little contiguous heap for a second 921600-byte allocation.
    auto* rgb=static_cast<unsigned char*>(network.GetPolarWorkspace(rgbBytes));
    if(!rgb){result.status="workspace_unavailable";return result;}
    std::unique_ptr<void,void(*)(void*)> storage(heap_caps_malloc(sizeof(polar::PipelineScratch),MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT),std::free);
    if(!storage){result.status="full_frame_memory_unavailable";return result;}
    if(std::fread(rgb,1,rgbBytes,frame.get())!=rgbBytes || std::fseek(vectors.get(),8,SEEK_SET)) {
        result.status="fixture_read_failed";return result;
    }
    auto* scratch=new(storage.get()) polar::PipelineScratch;
    const auto started=esp_timer_get_time();double inverse[6];
    if(polar::alignFrame(rgb,640,480,*scratch,inverse)!=polar::AlignmentStatus::Ok) {
        result.status="full_frame_alignment_rejected";return result;
    }
    result.alignmentUs=esp_timer_get_time()-started;
    bool same=true;int8_t expected[outputBytes],output[outputBytes],chunk[256];
    for(int i=0;i<6;++i) {
        vTaskDelay(1);auto begin=esp_timer_get_time();
        if(!polar::prepareDial(rgb,inverse,i,*scratch)){result.status="full_frame_preprocessing_rejected";return result;}
        result.preprocessingUs[i]=esp_timer_get_time()-begin;
        for(size_t offset=0;offset<inputBytes;offset+=sizeof(chunk)) {
            const size_t count=std::min(sizeof(chunk),inputBytes-offset);
            if(std::fread(chunk,1,count,vectors.get())!=count){result.status="fixture_read_failed";return result;}
            for(size_t j=0;j<count;++j)if(chunk[j]!=scratch->features[offset+j])++result.featureDifferences[i];
        }
        if(std::fread(expected,1,outputBytes,vectors.get())!=outputBytes){result.status="fixture_read_failed";return result;}
        begin=esp_timer_get_time();
        if(i==5 && !polar::loadRole(network,polar::ModelRole::Secondary)){
            result.status="secondary_model_rejected";return result;
        }
        if(!network.InferPolarScores(scratch->features,inputBytes,output,outputBytes)){result.status="inference_failed";return result;}
        result.inferenceUs[i]=esp_timer_get_time()-begin;
        for(size_t j=0;j<outputBytes;++j) {
            const int difference=std::abs(int(output[j])-int(expected[j]));
            if(difference)++result.differingBytes[i];
            result.maximumDifference[i]=std::max(result.maximumDifference[i],difference);
        }
        if(result.featureDifferences[i] || result.differingBytes[i])same=false;
        ++result.completed;
    }
    result.totalUs=esp_timer_get_time()-started;
    result.status=same?"full_frame_features_and_outputs_match":"full_frame_difference";
    return result;
}
