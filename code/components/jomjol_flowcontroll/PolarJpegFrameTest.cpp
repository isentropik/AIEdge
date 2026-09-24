#include "PolarRuntimeTest.h"
#include "PolarReplayCatalog.h"
#include "ProcessingAccess.h"
#include "../jomjol_controlcamera/CameraAccess.h"
#include "../jomjol_fileserver_ota/RuntimeBundle.h"
#include "CTfLiteClass.h"
#include "PolarPipeline.h"
#include "../jomjol_helper/psram.h"
#include "../stb/stb_image.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "mbedtls/sha256.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <memory>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <algorithm>
#include <new>

namespace {
using Buffer=std::unique_ptr<unsigned char,void(*)(void*)>;
Buffer buffer(size_t bytes) {
    return Buffer(static_cast<unsigned char*>(heap_caps_malloc(bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT)),std::free);
}
bool readFixture(const char* path,unsigned char* data,size_t bytes,const char* digest) {
    std::unique_ptr<FILE,int(*)(FILE*)> file(std::fopen(MeterBundle::runtimePath(path).c_str(),"rb"),std::fclose);
    if(!file || !data || std::fread(data,1,bytes,file.get())!=bytes ||
       std::fgetc(file.get())!=EOF || std::ferror(file.get()))return false;
    unsigned char hash[32];char hex[65]={};
    if(mbedtls_sha256(data,bytes,hash,0))return false;
    for(int i=0;i<32;++i)std::snprintf(hex+2*i,3,"%02x",hash[i]);
    return std::strcmp(hex,digest)==0;
}
struct DecodeMemory {
    bool owned=psram_init_shared_memory_for_take_image_step();
    ~DecodeMemory(){if(owned)psram_deinit_shared_memory_for_take_image_step();}
};
}

// Saved private JPEG only. No capture, settings change, publication or training.
// Decoder and model use the same shared PSRAM sequentially, never concurrently.
PolarRuntimeTestResult runPolarJpegFrameTest(int replayFrame) {
    PolarRuntimeTestResult result;result.jpegInput=true;result.replayFrame=replayFrame;
    if(replayFrame < -1 || replayFrame>=PolarReplay::count){result.status="replay_frame_rejected";return result;}
    ProcessingAccess processing;if(!processing){result.status="processing_busy";return result;}
    CameraAccess camera;if(!camera){result.status="camera_busy";return result;}
    constexpr size_t inputBytes=15360,outputBytes=360;
    size_t jpegBytes=57573;
    const char* jpegHash="b6c9a9a0bd291c053535c57fd4f9bf979c12f90ca00a6051a6d9d0de0d6d667b";
    const char* vectorsHash="a5bd8e61d2be7c94a40c9d9eaec9bab26f782cb931849aa9a50186db9122f919";
    std::string jpegPath="/sdcard/config/polar-runtime-frame.jpg",vectorsPath="/sdcard/config/polar-jpeg-vectors.bin";
    if(replayFrame>=0){
        const auto& frame=PolarReplay::frames[replayFrame];jpegBytes=frame.jpegBytes;
        jpegHash=frame.jpegHash;vectorsHash=frame.vectorsHash;
        char stem[64];std::snprintf(stem,sizeof(stem),"diagnostics/replay-%02d",replayFrame);
        jpegPath=MeterBundle::bootSelection().resolve(std::string(stem)+".jpg","");
        vectorsPath=MeterBundle::bootSelection().resolve(std::string(stem)+".bin","");
        if(jpegPath.empty()||vectorsPath.empty()){result.status="replay_assets_unavailable";return result;}
    }
    auto jpeg=buffer(jpegBytes),features=buffer(6*inputBytes);
    if(!jpeg || !features){result.status="jpeg_fixture_memory_unavailable";return result;}
    if(!readFixture(jpegPath.c_str(),jpeg.get(),jpegBytes,jpegHash)) {
        result.status="jpeg_fixture_rejected";return result;
    }
    const auto started=esp_timer_get_time();
    {
        DecodeMemory memory;if(!memory.owned){result.status="jpeg_shared_memory_busy";return result;}
        int width=0,height=0,channels=0;const auto decodeStart=esp_timer_get_time();
        std::unique_ptr<unsigned char,void(*)(void*)> rgb(
            stbi_load_from_memory(jpeg.get(),jpegBytes,&width,&height,&channels,STBI_rgb),stbi_image_free);
        result.decodeUs=esp_timer_get_time()-decodeStart;
        if(!rgb || width!=640 || height!=480){result.status="jpeg_decode_rejected";return result;}
        jpeg.reset();
        // JPEG temporaries are now freed. Reference vectors are loaded only
        // after this large scratch block is released, reducing peak heap use.
        auto storage=buffer(sizeof(polar::PipelineScratch));
        if(!storage){result.status="full_frame_memory_unavailable";return result;}
        auto*scratch=new(storage.get()) polar::PipelineScratch;
        double inverse[6];const auto alignmentStart=esp_timer_get_time();
        if(polar::alignFrame(rgb.get(),width,height,*scratch,inverse)!=polar::AlignmentStatus::Ok){
            result.status="full_frame_alignment_rejected";return result;
        }
        result.alignmentUs=esp_timer_get_time()-alignmentStart;
        for(int i=0;i<6;++i){
            vTaskDelay(1);const auto begin=esp_timer_get_time();
            if(!polar::prepareDial(rgb.get(),inverse,i,*scratch,&result.preprocessingProfile[i],esp_timer_get_time)){
                result.status="full_frame_preprocessing_rejected";return result;
            }
            result.preprocessingUs[i]=esp_timer_get_time()-begin;
            std::memcpy(features.get()+i*inputBytes,scratch->features,inputBytes);
        }
    } // Release RGB and shared decoder ownership before model allocation.
    auto vectors=buffer(8+6*(inputBytes+outputBytes));
    if(!vectors){result.status="jpeg_fixture_memory_unavailable";return result;}
    if(!readFixture(vectorsPath.c_str(),vectors.get(),8+6*(inputBytes+outputBytes),vectorsHash)){
        result.status="jpeg_fixture_rejected";return result;
    }
    CTfLiteClass network;
    if(!network.LoadFrozenPolarModel(MeterBundle::frozenModelPath("/sdcard/config/polar-int8.tflite")) ||
       !network.MakeAllocate() || !network.HasPolarTensorContract()){
        result.status="model_or_allocation_rejected";return result;
    }
    bool same=true;int8_t output[outputBytes];
    for(int i=0;i<6;++i){
        vTaskDelay(1);
        const auto*expectedFeatures=vectors.get()+8+i*(inputBytes+outputBytes);
        for(size_t j=0;j<inputBytes;++j)
            if(features.get()[i*inputBytes+j]!=expectedFeatures[j])++result.featureDifferences[i];
        const auto begin=esp_timer_get_time();
        if(!network.InferPolarScores(reinterpret_cast<int8_t*>(features.get()+i*inputBytes),inputBytes,output,outputBytes)){
            result.status="inference_failed";return result;
        }
        result.inferenceUs[i]=esp_timer_get_time()-begin;
        const auto*expected=reinterpret_cast<const int8_t*>(vectors.get()+8+i*(inputBytes+outputBytes)+inputBytes);
        for(size_t j=0;j<outputBytes;++j){
            const int difference=std::abs(int(output[j])-int(expected[j]));
            if(difference)++result.differingBytes[i];
            result.maximumDifference[i]=std::max(result.maximumDifference[i],difference);
        }
        if(result.featureDifferences[i] || result.differingBytes[i])same=false;
        ++result.completed;
    }
    result.totalUs=esp_timer_get_time()-started;
    result.status=same?"jpeg_frame_features_and_outputs_match":"jpeg_frame_difference";
    return result;
}
