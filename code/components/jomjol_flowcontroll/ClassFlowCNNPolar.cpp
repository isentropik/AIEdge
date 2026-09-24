#include "../jomjol_fileserver_ota/RuntimeBundle.h"
#include "ClassFlowCNNGeneral.h"
#include "CTfLiteClass.h"
#include "PolarPipeline.h"
#include "PolarAccounting.h"
#include "ClassLogFile.h"
#include "esp_timer.h"
#include "esp_task_wdt.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <cstring>
#include <limits>
#include <new>

namespace {
const char* TAG = "POLAR";
bool fail(const string& reason) {
    PolarAccounting::reject();
    LogFile.WriteToFile(ESP_LOG_ERROR, TAG, reason);
    return false;
}
}

bool ClassFlowCNNGeneral::validatePolarGeometry() {
    if (!flowpostalignment || !flowpostalignment->HasFrozenPolarAlignment()) return false;
    int index = 0;
    // Sequence order is significant for upstream carry handling. Require the
    // reviewed order as well as names, crops and direction; never silently sort.
    for (auto* group : GENERAL) {
        for (auto* item : group->ROI) {
            if (index >= 6) return false;
            const auto& expected = polar::dials[index++];
            if (group->name + "_" + item->name != expected.name ||
                item->posx != expected.x || item->posy != expected.y ||
                item->deltax != expected.w || item->deltay != expected.h ||
                item->CCW != expected.ccw) return false;
        }
    }
    return index == 6;
}

bool ClassFlowCNNGeneral::doPolarNetwork(string time) {
    // Publish all six results together only after every check succeeds. A failed
    // frame cannot retain some readings from this frame and some from the last.
    for (auto* group : GENERAL) for (auto* item : group->ROI) {
        item->isReject = true;
        item->result_float = std::numeric_limits<float>::quiet_NaN();
    }
    if (!validatePolarGeometry()) return fail("Geometry changed; PolarV1 refused frame");
    CAlignAndCutImage* image = flowpostalignment->GetAlignAndCutImage();
    if (!image || image->width != 640 || image->height != 480 ||
        image->channels != 3 || !image->rgb_image)
        return fail("PolarV1 requires a 640x480 RGB aligned-stage image");

    CTfLiteClass network;
    if (!network.LoadFrozenPolarModel(MeterBundle::frozenModelPath(FormatFileName("/sdcard" + cnnmodelfile))))
        return fail("Frozen model hash/length/read rejected");
    if (!network.MakeAllocate() || !network.HasPolarTensorContract())
        return fail("PolarV1 tensor allocation/contract rejected");
    void* storage = network.GetPolarWorkspace(sizeof(polar::PipelineScratch));
    if (!storage) return fail("No reserved polar workspace available");
    // POD scratch has no resources/destructor. Its lifetime ends with the model
    // region, after inference; no extra full-frame RGB allocation is made.
    auto* scratch = new (storage) polar::PipelineScratch;
    const int64_t started = esp_timer_get_time();
    double inverse[6];
    const auto alignment = polar::alignFrame(image->rgb_image,640,480,*scratch,inverse);
    if (alignment != polar::AlignmentStatus::Ok)
        return fail("Marker registration rejected: " + std::to_string(static_cast<int>(alignment)));
    const int64_t aligned = esp_timer_get_time();
    float readings[6];
    int index = 0;
    for (auto* group : GENERAL) {
        for (auto* item : group->ROI) {
            esp_task_wdt_reset();
            vTaskDelay(1);
            const int64_t beginDial = esp_timer_get_time();
            scratch->visibilityScore = -1;
            // Use the hardware-checked even-grid warp; crop coordinates and
            // the fixed needle pivot remain unchanged. Dense sampling remains
            // available in the replay endpoint for regression comparisons.
            if (!polar::prepareDial(image->rgb_image,inverse,index,*scratch,nullptr,nullptr,true))
                return fail(string(polar::dials[index].name) + ": " + polar::preparationStatusName(scratch->preparationStatus));
            const int64_t prepared = esp_timer_get_time();
            if (!network.InferPolar(scratch->features,384*40,item->CCW,readings[index]))
                return fail(string(polar::dials[index].name) + ": inference rejected");
            const int64_t inferred = esp_timer_get_time();
            if (!item->image_org || !item->image_org->rgb_image || !item->image || !item->image->rgb_image)
                return fail("ROI preview allocation missing");
            // Preview only. Neither RGB resize nor preview pixels feed inference.
            std::memcpy(item->image_org->rgb_image,scratch->crop,item->deltax*item->deltay*3);
            item->image_org->Resize(modelxsize,modelysize,item->image);
            LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, string(polar::dials[index].name) +
                " preprocess_us=" + std::to_string(prepared-beginDial) +
                " inference_us=" + std::to_string(inferred-prepared));
            ++index;
        }
    }
    index = 0;
    PolarAccounting::observe(readings,image->captureMonotonicUs,image->captureTimestampValid);
    const auto accounting=PolarAccounting::snapshot();
    LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, string("accounting_state=") +
        meter::sessionStateName(accounting.state) + " interval_status=" +
        meter::intervalStatusName(accounting.interval.status));
    for (auto* group : GENERAL) for (auto* item : group->ROI) {
        item->result_float = readings[index++];
        item->isReject = false;
    }
    LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "registration_us=" + std::to_string(aligned-started) +
        " polar_total_us=" + std::to_string(esp_timer_get_time()-started) +
        " sampling=even_grid workspace_bytes=" + std::to_string(sizeof(polar::PipelineScratch)));
    RemoveOldLogs();
    return true;
}
