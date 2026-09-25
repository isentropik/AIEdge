#include "PolarModelRouting.h"
#include "../jomjol_controlcamera/CameraAccess.h"
#include "../jomjol_fileserver_ota/RuntimeBundle.h"
#include "PolarRuntimeTest.h"
#include "ProcessingAccess.h"
#include "CTfLiteClass.h"
#include "esp_timer.h"
#include "esp_task_wdt.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mbedtls/sha256.h"
#include <cstdio>
#include <cstring>
#include <algorithm>
#include <cstdlib>

PolarRuntimeTestResult runPolarRuntimeTest() {
    PolarRuntimeTestResult result;
    ProcessingAccess access;
    if(!access){result.status="processing_busy";return result;}
    CameraAccess camera;
    if(!camera){result.status="camera_busy";return result;}
    CTfLiteClass network;
    if(!polar::loadRole(network,polar::ModelRole::Main)) {
        result.status="model_or_allocation_rejected";return result;
    }
    constexpr size_t inputBytes=384*40,outputBytes=360;
    constexpr size_t fixtureBytes=8+6*(inputBytes+outputBytes);
    auto* fixture=static_cast<unsigned char*>(network.GetPolarWorkspace(fixtureBytes));
    if(!fixture){result.status="workspace_unavailable";return result;}
    FILE* file=std::fopen(MeterBundle::runtimePath("/sdcard/config/polar-runtime-vectors.bin").c_str(),"rb");
    if(!file){result.status="fixture_unavailable";return result;}
    bool readOk=std::fread(fixture,1,fixtureBytes,file)==fixtureBytes;
    if(readOk) readOk=std::fgetc(file)==EOF && !std::ferror(file);
    if(std::fclose(file)!=0)readOk=false;
    if(!readOk){result.status="fixture_length_or_read_error";return result;}
    // Fixed vectors exported from the held-out frame; expected outputs are
    // desktop runtime results, not labels or proof of meter reading accuracy.
    const unsigned char expectedHash[32]={0x76,0x59,0x2a,0x50,0x85,0x1b,0xe4,0xc2,0x37,0x85,0x2a,0xe5,0xd6,0xeb,0x2e,0x3d,0x85,0xf4,0xa2,0x90,0xfa,0x94,0x95,0xcc,0xca,0x9c,0x4c,0x5c,0x19,0x5a,0xc1,0x75};
    unsigned char hash[32];
    if(mbedtls_sha256(fixture,fixtureBytes,hash,0)!=0 ||
       std::memcmp(hash,expectedHash,32) || std::memcmp(fixture,"PLRTEST1",8)) {
        result.status="fixture_hash_rejected";return result;
    }
    int8_t output[outputBytes];bool same=true;
    for(int i=0;i<6;++i) {
        esp_task_wdt_reset();vTaskDelay(1);
        const auto* input=reinterpret_cast<const int8_t*>(fixture+8+i*(inputBytes+outputBytes));
        const auto* expected=input+inputBytes;
        const int64_t start=esp_timer_get_time();
        if(i==5 && !polar::loadRole(network,polar::ModelRole::Secondary)){
            result.status="secondary_model_rejected";return result;
        }
        if(!network.InferPolarScores(input,inputBytes,output,outputBytes)) {
            result.status="inference_failed";return result;
        }
        result.inferenceUs[i]=esp_timer_get_time()-start;
        for(size_t j=0;j<outputBytes;++j) {
            const int difference=std::abs(int(output[j])-int(expected[j]));
            if(difference)++result.differingBytes[i];
            result.maximumDifference[i]=std::max(result.maximumDifference[i],difference);
        }
        if(result.differingBytes[i])same=false;
        ++result.completed;
    }
    result.status=same ? "all_output_bytes_match" : "output_difference";
    return result;
}
