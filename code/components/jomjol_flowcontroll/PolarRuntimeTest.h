#pragma once
#include <cstdint>
#include "../jomjol_tfliteclass/PolarProfile.h"
struct PolarRuntimeTestResult {
    const char* status="not_run";
    int completed=0;
    int differingBytes[6]={};
    int maximumDifference[6]={};
    int64_t inferenceUs[6]={};
    int64_t alignmentUs=0,totalUs=0,preprocessingUs[6]={};
    int featureDifferences[6]={};
    polar::DialProfile preprocessingProfile[6];
    bool jpegInput=false;
    int replayFrame=-1;
    bool sparseSampling=false;
    int64_t decodeUs=0;
};
PolarRuntimeTestResult runPolarRuntimeTest();

PolarRuntimeTestResult runPolarFullFrameTest();
PolarRuntimeTestResult runPolarJpegFrameTest(int replayFrame=-1);
