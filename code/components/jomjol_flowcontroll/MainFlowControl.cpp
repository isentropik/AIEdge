#include "TelemetryBootIdentity.h"
#include "ImageArchiveStatus.h"
#include "ImageArchiveStartup.h"
#include "ImageArchiveSettingsHttp.h"
#include "MeterProfileSettingsHttp.h"
#include "ProcessingAccess.h"
#include "FileConfigStorage.h"
#include "MainFlowControl.h"

#include <string>
#include <atomic>
#include <new>
#include <vector>
#include "string.h"
#include "esp_log.h"
#include <esp_timer.h>

#include <iomanip>
#include <sstream>

#include "../../include/defines.h"
#include "Helper.h"
#include "statusled.h"

#include "esp_camera.h"
#include "time_sntp.h"
#include "ClassControllCamera.h"
#include "CameraAccess.h"
#include "StreamPreview.h"
#include "CycleTelemetry.h"
#include "../jomjol_fileserver_ota/OtaHealthPolicy.h"
#include "../jomjol_fileserver_ota/RuntimeBundle.h"
#include "esp_ota_ops.h"
#include "../jomjol_fileserver_ota/UpdateAccess.h"
#include "CycleSchedule.h"
#include "PolarAccounting.h"
#include "MeterStatus.h"
#include "MeterHistoryFiles.h"
#include "PolarRuntimeTest.h"
#include "PolarReplayCatalog.h"

#include "ClassFlowControll.h"

#include "ClassLogFile.h"
#include "server_GPIO.h"

#include "server_file.h"

#include "read_wlanini.h"
#include "connect_wlan.h"
#include "psram.h"
#include "basic_auth.h"

// support IDF 5.x
#ifndef portTICK_RATE_MS
#define portTICK_RATE_MS portTICK_PERIOD_MS
#endif

ClassFlowControll flowctrl;
camera_flow_config_temp_t CFstatus;

TaskHandle_t xHandletask_autodoFlow = NULL;

bool bTaskAutoFlowCreated = false;
bool flowisrunning = false;

long auto_interval = 0;
bool autostartIsEnabled = false;

int countRounds = 0;
bool isPlannedReboot = false;

static const char *TAG = "MAINCTRL";

// #define DEBUG_DETAIL_ON

void CheckIsPlannedReboot(void)
{
    FILE *pfile;

    if ((pfile = fopen("/sdcard/reboot.txt", "r")) == NULL)
    {
        // LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "Initial boot or not a planned reboot");
        isPlannedReboot = false;
    }
    else
    {
        LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "Planned reboot");
        DeleteFile("/sdcard/reboot.txt"); // Prevent Boot Loop!!!
        isPlannedReboot = true;
    }
}

bool getIsPlannedReboot(void)
{
    return isPlannedReboot;
}

int getCountFlowRounds(void)
{
    return countRounds;
}

esp_err_t GetJPG(std::string _filename, httpd_req_t *req)
{
    return flowctrl.GetJPGStream(_filename, req);
}

esp_err_t GetRawJPG(httpd_req_t *req)
{
    return flowctrl.SendRawJPG(req);
}

bool isSetupModusActive(void)
{
    return flowctrl.getStatusSetupModus();
}

void DeleteMainFlowTask(void)
{
#ifdef DEBUG_DETAIL_ON
    ESP_LOGD(TAG, "DeleteMainFlowTask: xHandletask_autodoFlow: %ld", (long)xHandletask_autodoFlow);
#endif

    if (xHandletask_autodoFlow != NULL)
    {
        vTaskDelete(xHandletask_autodoFlow);
        xHandletask_autodoFlow = NULL;
    }

#ifdef DEBUG_DETAIL_ON
    ESP_LOGD(TAG, "Killed: xHandletask_autodoFlow");
#endif
}

void doInit(void)
{
#ifdef DEBUG_DETAIL_ON
    ESP_LOGD(TAG, "Start flowctrl.InitFlow(config);");
#endif
    flowctrl.InitFlow(CONFIG_FILE);
#ifdef DEBUG_DETAIL_ON
    ESP_LOGD(TAG, "Finished flowctrl.InitFlow(config);");
#endif

    /* GPIO handler has to be initialized before MQTT init to ensure proper topic subscription */
    gpio_handler_init();

    {
        ProcessingAccess processing;
        CameraAccess camera(pdMS_TO_TICKS(1000));
        if(processing && camera && ConfigStorage::safe().load())
            LogFile.WriteToFile(ESP_LOG_INFO,TAG,ImageArchive::startConfiguredArchive(flowctrl.hasFrozenArchiveProfile()));
    }


#ifdef ENABLE_MQTT
    flowctrl.StartMQTTService();
#endif // ENABLE_MQTT
}

bool doflow(void)
{
    std::string zw_time = getCurrentTimeString(LOGFILE_TIME_FORMAT);
    ESP_LOGD(TAG, "doflow - start %s", zw_time.c_str());
    flowisrunning = true;
    const bool succeeded = flowctrl.doFlow(zw_time);
    flowisrunning = false;

#ifdef DEBUG_DETAIL_ON
    ESP_LOGD(TAG, "doflow - end %s", zw_time.c_str());
#endif

    return succeeded;
}

esp_err_t setCCstatusToCFstatus(void)
{
    CFstatus.CamSensor_id = CCstatus.CamSensor_id;

    CFstatus.ImageFrameSize = CCstatus.ImageFrameSize;

    CFstatus.ImageContrast = CCstatus.ImageContrast;
    CFstatus.ImageBrightness = CCstatus.ImageBrightness;
    CFstatus.ImageSaturation = CCstatus.ImageSaturation;

    CFstatus.ImageQuality = CCstatus.ImageQuality;

    CFstatus.ImageGainceiling = CCstatus.ImageGainceiling;

    CFstatus.ImageAgc = CCstatus.ImageAgc;
    CFstatus.ImageAec = CCstatus.ImageAec;
    CFstatus.ImageHmirror = CCstatus.ImageHmirror;
    CFstatus.ImageVflip = CCstatus.ImageVflip;

    CFstatus.ImageAwb = CCstatus.ImageAwb;
    CFstatus.ImageAec2 = CCstatus.ImageAec2;
    CFstatus.ImageAecValue = CCstatus.ImageAecValue;
    CFstatus.ImageSpecialEffect = CCstatus.ImageSpecialEffect;
    CFstatus.ImageWbMode = CCstatus.ImageWbMode;
    CFstatus.ImageAeLevel = CCstatus.ImageAeLevel;

    CFstatus.ImageDcw = CCstatus.ImageDcw;
    CFstatus.ImageBpc = CCstatus.ImageBpc;
    CFstatus.ImageWpc = CCstatus.ImageWpc;
    CFstatus.ImageAwbGain = CCstatus.ImageAwbGain;
    CFstatus.ImageAgcGain = CCstatus.ImageAgcGain;

    CFstatus.ImageRawGma = CCstatus.ImageRawGma;
    CFstatus.ImageLenc = CCstatus.ImageLenc;

    CFstatus.ImageSharpness = CCstatus.ImageSharpness;
    CFstatus.ImageAutoSharpness = CCstatus.ImageAutoSharpness;

    CFstatus.ImageDenoiseLevel = CCstatus.ImageDenoiseLevel;

    CFstatus.ImageLedIntensity = CCstatus.ImageLedIntensity;

    CFstatus.ImageZoomEnabled = CCstatus.ImageZoomEnabled;
    CFstatus.ImageZoomOffsetX = CCstatus.ImageZoomOffsetX;
    CFstatus.ImageZoomOffsetY = CCstatus.ImageZoomOffsetY;
    CFstatus.ImageZoomSize = CCstatus.ImageZoomSize;

    CFstatus.WaitBeforePicture = CCstatus.WaitBeforePicture;

    return ESP_OK;
}

esp_err_t setCFstatusToCCstatus(void)
{
    // CCstatus.CamSensor_id = CFstatus.CamSensor_id;

    CCstatus.ImageFrameSize = CFstatus.ImageFrameSize;

    CCstatus.ImageContrast = CFstatus.ImageContrast;
    CCstatus.ImageBrightness = CFstatus.ImageBrightness;
    CCstatus.ImageSaturation = CFstatus.ImageSaturation;

    CCstatus.ImageQuality = CFstatus.ImageQuality;

    CCstatus.ImageGainceiling = CFstatus.ImageGainceiling;

    CCstatus.ImageAgc = CFstatus.ImageAgc;
    CCstatus.ImageAec = CFstatus.ImageAec;
    CCstatus.ImageHmirror = CFstatus.ImageHmirror;
    CCstatus.ImageVflip = CFstatus.ImageVflip;

    CCstatus.ImageAwb = CFstatus.ImageAwb;
    CCstatus.ImageAec2 = CFstatus.ImageAec2;
    CCstatus.ImageAecValue = CFstatus.ImageAecValue;
    CCstatus.ImageSpecialEffect = CFstatus.ImageSpecialEffect;
    CCstatus.ImageWbMode = CFstatus.ImageWbMode;
    CCstatus.ImageAeLevel = CFstatus.ImageAeLevel;

    CCstatus.ImageDcw = CFstatus.ImageDcw;
    CCstatus.ImageBpc = CFstatus.ImageBpc;
    CCstatus.ImageWpc = CFstatus.ImageWpc;
    CCstatus.ImageAwbGain = CFstatus.ImageAwbGain;
    CCstatus.ImageAgcGain = CFstatus.ImageAgcGain;

    CCstatus.ImageRawGma = CFstatus.ImageRawGma;
    CCstatus.ImageLenc = CFstatus.ImageLenc;

    CCstatus.ImageSharpness = CFstatus.ImageSharpness;
    CCstatus.ImageAutoSharpness = CFstatus.ImageAutoSharpness;

    CCstatus.ImageDenoiseLevel = CFstatus.ImageDenoiseLevel;

    CCstatus.ImageLedIntensity = CFstatus.ImageLedIntensity;

    CCstatus.ImageZoomEnabled = CFstatus.ImageZoomEnabled;
    CCstatus.ImageZoomOffsetX = CFstatus.ImageZoomOffsetX;
    CCstatus.ImageZoomOffsetY = CFstatus.ImageZoomOffsetY;
    CCstatus.ImageZoomSize = CFstatus.ImageZoomSize;

    CCstatus.WaitBeforePicture = CFstatus.WaitBeforePicture;

    return ESP_OK;
}

esp_err_t setCFstatusToCam(void)
{
    sensor_t *s = esp_camera_sensor_get();

    if (s != NULL)
    {
        s->set_framesize(s, CFstatus.ImageFrameSize);

        // s->set_contrast(s, CFstatus.ImageContrast);     // -2 to 2
        // s->set_brightness(s, CFstatus.ImageBrightness); // -2 to 2
        Camera.SetCamContrastBrightness(s, CFstatus.ImageContrast, CFstatus.ImageBrightness);
		
        s->set_saturation(s, CFstatus.ImageSaturation); // -2 to 2

        s->set_quality(s, CFstatus.ImageQuality); // 0 - 63

        // s->set_gainceiling(s, CFstatus.ImageGainceiling); // Image gain (GAINCEILING_x2, x4, x8, x16, x32, x64 or x128)
        Camera.SetCamGainceiling(s, CFstatus.ImageGainceiling);

        s->set_gain_ctrl(s, CFstatus.ImageAgc);     // 0 = disable , 1 = enable
        s->set_exposure_ctrl(s, CFstatus.ImageAec); // 0 = disable , 1 = enable
        s->set_hmirror(s, CFstatus.ImageHmirror);   // 0 = disable , 1 = enable
        s->set_vflip(s, CFstatus.ImageVflip);       // 0 = disable , 1 = enable

        s->set_whitebal(s, CFstatus.ImageAwb);       // 0 = disable , 1 = enable
        s->set_aec2(s, CFstatus.ImageAec2);          // 0 = disable , 1 = enable
        s->set_aec_value(s, CFstatus.ImageAecValue); // 0 to 1200
        // s->set_special_effect(s, CFstatus.ImageSpecialEffect); // 0 to 6 (0 - No Effect, 1 - Negative, 2 - Grayscale, 3 - Red Tint, 4 - Green Tint, 5 - Blue Tint, 6 - Sepia)
        Camera.SetCamSpecialEffect(s, CFstatus.ImageSpecialEffect);
        s->set_wb_mode(s, CFstatus.ImageWbMode);   // 0 to 4 - if awb_gain enabled (0 - Auto, 1 - Sunny, 2 - Cloudy, 3 - Office, 4 - Home)
        s->set_ae_level(s, CFstatus.ImageAeLevel); // -2 to 2

        s->set_dcw(s, CFstatus.ImageDcw);          // 0 = disable , 1 = enable
        s->set_bpc(s, CFstatus.ImageBpc);          // 0 = disable , 1 = enable
        s->set_wpc(s, CFstatus.ImageWpc);          // 0 = disable , 1 = enable
        s->set_awb_gain(s, CFstatus.ImageAwbGain); // 0 = disable , 1 = enable
        s->set_agc_gain(s, CFstatus.ImageAgcGain); // 0 to 30

        s->set_raw_gma(s, CFstatus.ImageRawGma); // 0 = disable , 1 = enable
        s->set_lenc(s, CFstatus.ImageLenc);      // 0 = disable , 1 = enable

        // s->set_sharpness(s, CFstatus.ImageSharpness);   // auto-sharpness is not officially supported, default to 0
        Camera.SetCamSharpness(CFstatus.ImageAutoSharpness, CFstatus.ImageSharpness);
        s->set_denoise(s, CFstatus.ImageDenoiseLevel); // The OV2640 does not support it, OV3660 and OV5640 (0 to 8)

        TickType_t xDelay2 = 100 / portTICK_PERIOD_MS;
        vTaskDelay(xDelay2);

        return ESP_OK;
    }
    else
    {
        return ESP_FAIL;
    }
}

esp_err_t handler_cycle_timing(httpd_req_t* req)
{
    const std::string bootId=CycleTelemetry::bootIdentity();
    const auto data = CycleTelemetry::snapshot();
    const auto& last = data.last;
    std::string json = "{\"clock\":\"monotonic_us_since_boot\",\"target_us\":30000000,\"active\":";
    json += data.active ? "true" : "false";
    json += ",\"boot_id\":\"" + bootId + "\"";
    json += ",\"attempts\":" + std::to_string(data.attempts) +
        ",\"pipeline_completed\":" + std::to_string(data.completed) +
        ",\"accepted_reader_cycles\":" + std::to_string(data.acceptedReaderCycles) +
        ",\"accepted_reader_streak\":" + std::to_string(data.acceptedReaderStreak) +
        ",\"failed\":" + std::to_string(data.failed) +
        ",\"overlaps_rejected\":" + std::to_string(data.overlapsRejected) +
        ",\"over_target\":" + std::to_string(data.overTarget) +
        ",\"missed_schedule_slots\":" + std::to_string(data.missedScheduleSlots) +
        ",\"valid_readings\":null,\"last\":{\"start_us\":" + std::to_string(last.startedUs) +
        ",\"end_us\":" + std::to_string(last.finishedUs) +
        ",\"capture_us\":" + std::to_string(last.capturedUs) +
        ",\"capture_interval_us\":" + std::to_string(last.captureIntervalUs) +
        ",\"reader_accepted\":" + (last.readerAccepted ? "true" : "false") +
        ",\"stage_attempts\":" + std::to_string(last.attempts) +
        ",\"pipeline_completed\":" + (last.pipelineCompleted ? "true" : "false") + ",\"stages\":[";
    for (int i=0; i<last.storedStages; ++i) {
        if (i) json += ",";
        const auto& stage = last.stages[i];
        json += "{\"index\":" + std::to_string(stage.index) +
            ",\"duration_us\":" + std::to_string(stage.durationUs) +
            ",\"ok\":" + (stage.ok ? "true" : "false") + "}";
    }
    json += "]}}";
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_send(req, json.c_str(), json.size());
}

esp_err_t handler_image_archive_status(httpd_req_t* req)
{
    const auto& binding=ImageArchive::captureBinding();
    const auto json=ImageArchive::archiveStatusJson(ImageArchive::archiveWorkerStatus(),
        binding.enabled.load(std::memory_order_acquire),binding.rejected.load());
    httpd_resp_set_type(req,"application/json");
    httpd_resp_set_hdr(req,"Cache-Control","no-store");
    return httpd_resp_send(req,json.c_str(),json.size());
}

esp_err_t handler_meter_accounting(httpd_req_t* req)
{
    const auto json=meter::statusJson(PolarAccounting::snapshot());
    httpd_resp_set_type(req,"application/json");
    httpd_resp_set_hdr(req,"Cache-Control","no-store");
    return httpd_resp_send(req,json.c_str(),json.size());
}

// One explicitly requested diagnostic at a time. Never retain the HTTP request
// in the worker; the server can serve status while the model is running.
static portMUX_TYPE historyMux=portMUX_INITIALIZER_UNLOCKED;
static bool historyActive=false;
static meter::HistorySummary historySummary;
static int64_t historyScannedUs=0;
static void historyWorker(void*) {
    meter::HistorySummary result;
    {
        ProcessingAccess processing;
        if(!processing)result.reason="processing_busy";
        else {
            UpdateAccess update;
            if(!update)result.reason="storage_busy";
            else result=meter::readSegmentHistory("/sdcard/config","polar-meter-reference",
                polar::modelIdentity,polar::geometryIdentity,PolarAccounting::snapshot().assumptions);
        }
    }
    const auto finished=esp_timer_get_time();
    portENTER_CRITICAL(&historyMux);
    historySummary=result;historyScannedUs=finished;historyActive=false;
    portEXIT_CRITICAL(&historyMux);
    vTaskDelete(nullptr);
}
esp_err_t handler_meter_history_refresh(httpd_req_t* req) {
    httpd_resp_set_type(req,"application/json");httpd_resp_set_hdr(req,"Cache-Control","no-store");
    if(req->content_len||httpd_req_get_url_query_len(req)){
        httpd_resp_set_status(req,"400 Bad Request");return httpd_resp_sendstr(req,"{\"status\":\"empty_request_required\"}");
    }
    portENTER_CRITICAL(&historyMux);
    const bool busy=historyActive;
    if(!busy){historyActive=true;historySummary=meter::HistorySummary{};historySummary.reason="scan_pending";historyScannedUs=0;}
    portEXIT_CRITICAL(&historyMux);
    if(busy){httpd_resp_set_status(req,"409 Conflict");return httpd_resp_sendstr(req,"{\"status\":\"scan_active\"}");}
    if(xTaskCreate(historyWorker,"meter_history",8192,nullptr,1,nullptr)!=pdPASS){
        portENTER_CRITICAL(&historyMux);historyActive=false;historySummary.reason="task_creation_failed";portEXIT_CRITICAL(&historyMux);
        httpd_resp_set_status(req,"503 Service Unavailable");return httpd_resp_sendstr(req,"{\"status\":\"task_creation_failed\"}");
    }
    httpd_resp_set_status(req,"202 Accepted");return httpd_resp_sendstr(req,"{\"status\":\"accepted\"}");
}
esp_err_t handler_meter_history_status(httpd_req_t* req) {
    portENTER_CRITICAL(&historyMux);
    const auto result=historySummary;const bool active=historyActive;const auto scanned=historyScannedUs;
    portEXIT_CRITICAL(&historyMux);
    const std::string json=std::string("{\"active\":")+(active?"true":"false")+
        ",\"valid\":"+(result.valid?"true":"false")+",\"reason\":\""+result.reason+"\",\"scope\":\"completed_segments_only\","+
        "\"scanned_at_uptime_us\":"+std::to_string(scanned)+",\"segments\":"+std::to_string(result.segments)+
        ",\"duplicates\":"+std::to_string(result.duplicates)+",\"covered_minimum_ft3\":"+(result.valid?meter::jsonNumber(result.coveredMinimumFt3):"null")+
        ",\"covered_maximum_ft3\":"+(result.valid?meter::jsonNumber(result.coveredMaximumFt3):"null")+
        ",\"lifetime_complete\":false,\"verified_accuracy\":false}";
    httpd_resp_set_type(req,"application/json");httpd_resp_set_hdr(req,"Cache-Control","no-store");
    return httpd_resp_send(req,json.c_str(),json.size());
}

static portMUX_TYPE polarTestMux = portMUX_INITIALIZER_UNLOCKED;
static bool polarTestActive = false;
static PolarRuntimeTestResult polarTestResult;

static void polarTestWorker(void*)
{
    const auto result = runPolarRuntimeTest();
    portENTER_CRITICAL(&polarTestMux);
    polarTestResult = result;
    polarTestActive = false;
    portEXIT_CRITICAL(&polarTestMux);
    vTaskDelete(nullptr);
}

esp_err_t handler_polar_test_start(httpd_req_t* req)
{
    httpd_resp_set_type(req,"application/json");
    httpd_resp_set_hdr(req,"Cache-Control","no-store");
    if(req->content_len || httpd_req_get_url_query_len(req)) {
        httpd_resp_set_status(req,"400 Bad Request");
        return httpd_resp_sendstr(req,"{\"status\":\"empty_request_required\"}");
    }
    portENTER_CRITICAL(&polarTestMux);
    const bool busy = polarTestActive;
    if(!busy) {
        polarTestActive = true;
        polarTestResult = PolarRuntimeTestResult{};
        polarTestResult.status = "queued_or_running";
    }
    portEXIT_CRITICAL(&polarTestMux);
    if(busy) {
        httpd_resp_set_status(req,"409 Conflict");
        return httpd_resp_sendstr(req,"{\"status\":\"diagnostic_active\"}");
    }
    if(xTaskCreate(polarTestWorker,"polar_test",8192,nullptr,1,nullptr)!=pdPASS) {
        portENTER_CRITICAL(&polarTestMux);
        polarTestResult.status = "task_creation_failed";
        polarTestActive = false;
        portEXIT_CRITICAL(&polarTestMux);
        httpd_resp_set_status(req,"503 Service Unavailable");
        return httpd_resp_sendstr(req,"{\"status\":\"task_creation_failed\"}");
    }
    httpd_resp_set_status(req,"202 Accepted");
    return httpd_resp_sendstr(req,"{\"status\":\"accepted\",\"result_url\":\"/polar_runtime_test\"}");
}

esp_err_t handler_polar_test_status(httpd_req_t* req)
{
    portENTER_CRITICAL(&polarTestMux);
    const auto result = polarTestResult;
    const bool active = polarTestActive;
    portEXIT_CRITICAL(&polarTestMux);
    std::string json = "{\"active\":" + std::string(active ? "true" : "false") +
        ",\"status\":\"" + result.status + "\",\"verified_accuracy\":false,\"completed\":" +
        std::to_string(result.completed) + ",\"replay_frame\":"+std::to_string(result.replayFrame)+",\"sparse_sampling\":"+(result.sparseSampling?"true":"false")+",\"dials\":[";
    for(int i=0;i<result.completed;++i) {
        if(i)json += ",";
        json += "{\"index\":" + std::to_string(i) +
            ",\"differing_bytes\":" + std::to_string(result.differingBytes[i]) +
            ",\"maximum_difference\":" + std::to_string(result.maximumDifference[i]) +
            ",\"inference_us\":" + std::to_string(result.inferenceUs[i]) + "}";
    }
    json += "]}";
    httpd_resp_set_type(req,"application/json");
    httpd_resp_set_hdr(req,"Cache-Control","no-store");
    return httpd_resp_send(req,json.c_str(),json.size());
}

static portMUX_TYPE polarFrameTestMux = portMUX_INITIALIZER_UNLOCKED;
static bool polarFrameTestActive = false;
static PolarRuntimeTestResult polarFrameTestResult;

static void polarFrameTestWorker(void* jpeg)
{
    const auto mode=reinterpret_cast<intptr_t>(jpeg);
    const auto result = mode ? runPolarJpegFrameTest(static_cast<int>(mode)-2) : runPolarFullFrameTest();
    portENTER_CRITICAL(&polarFrameTestMux);
    polarFrameTestResult = result;
    polarFrameTestActive = false;
    portEXIT_CRITICAL(&polarFrameTestMux);
    vTaskDelete(nullptr);
}

esp_err_t handler_polar_frame_test_start(httpd_req_t* req)
{
    const std::string uri(req->uri);
    const bool jpeg=uri.substr(0,uri.find('?'))=="/polar_jpeg_test";
    httpd_resp_set_type(req,"application/json");
    httpd_resp_set_hdr(req,"Cache-Control","no-store");
    int frame=-1;char query[32]={};
    const auto queryLength=httpd_req_get_url_query_len(req);
    if(req->content_len || (queryLength && (!jpeg || queryLength>=sizeof(query) ||
       httpd_req_get_url_query_str(req,query,sizeof(query))!=ESP_OK || !PolarReplay::parse(query,frame)))) {
        httpd_resp_set_status(req,"400 Bad Request");
        return httpd_resp_sendstr(req,"{\"status\":\"invalid_replay_request\"}");
    }
    portENTER_CRITICAL(&polarFrameTestMux);
    const bool busy = polarFrameTestActive;
    if(!busy) {
        polarFrameTestActive = true;
        polarFrameTestResult = PolarRuntimeTestResult{};
        polarFrameTestResult.status = "queued_or_running";
        polarFrameTestResult.jpegInput = jpeg;
        polarFrameTestResult.replayFrame=frame>=PolarReplay::count?frame-PolarReplay::count:frame;
        polarFrameTestResult.sparseSampling=frame>=PolarReplay::count;
    }
    portEXIT_CRITICAL(&polarFrameTestMux);
    if(busy) {
        httpd_resp_set_status(req,"409 Conflict");
        return httpd_resp_sendstr(req,"{\"status\":\"diagnostic_active\"}");
    }
    if(xTaskCreate(polarFrameTestWorker,"polar_frame_test",8192,jpeg?reinterpret_cast<void*>(static_cast<intptr_t>(frame+2)):nullptr,1,nullptr)!=pdPASS) {
        portENTER_CRITICAL(&polarFrameTestMux);
        polarFrameTestResult.status = "task_creation_failed";
        polarFrameTestActive = false;
        portEXIT_CRITICAL(&polarFrameTestMux);
        httpd_resp_set_status(req,"503 Service Unavailable");
        return httpd_resp_sendstr(req,"{\"status\":\"task_creation_failed\"}");
    }
    httpd_resp_set_status(req,"202 Accepted");
    if(jpeg)return httpd_resp_sendstr(req,"{\"status\":\"accepted\",\"result_url\":\"/polar_jpeg_test\"}");
    return httpd_resp_sendstr(req,"{\"status\":\"accepted\",\"result_url\":\"/polar_frame_test\"}");
}

esp_err_t handler_polar_frame_test_status(httpd_req_t* req)
{
    portENTER_CRITICAL(&polarFrameTestMux);
    const auto result = polarFrameTestResult;
    const bool active = polarFrameTestActive;
    portEXIT_CRITICAL(&polarFrameTestMux);
    std::string json = "{\"active\":" + std::string(active ? "true" : "false") +
        ",\"status\":\"" + result.status + "\",\"verified_accuracy\":false,\"completed\":" +
        std::to_string(result.completed) + ",\"replay_frame\":"+std::to_string(result.replayFrame)+",\"sparse_sampling\":"+(result.sparseSampling?"true":"false")+",\"dials\":[";
    for(int i=0;i<result.completed;++i) {
        if(i)json += ",";
        json += "{\"index\":" + std::to_string(i) +
            ",\"differing_bytes\":" + std::to_string(result.differingBytes[i]) +
            ",\"maximum_difference\":" + std::to_string(result.maximumDifference[i]) +
            ",\"inference_us\":" + std::to_string(result.inferenceUs[i]) + "}";
    }
    json += "],\"scope\":\""+std::string(result.jpegInput?"held_out_jpeg_frame":"held_out_rgb_frame")+"\",\"jpeg_decode_us\":"+std::to_string(result.decodeUs)+",\"camera_capture_tested\":false,\"alignment_us\":"+std::to_string(result.alignmentUs)+",\"total_processing_us\":"+std::to_string(result.totalUs)+",\"features\":[";
    for(int i=0;i<result.completed;++i){if(i)json+=",";json+="{\"index\":"+std::to_string(i)+",\"differing_bytes\":"+std::to_string(result.featureDifferences[i])+",\"preprocessing_us\":"+std::to_string(result.preprocessingUs[i])+"}";}
    json += "],\"preprocessing_profile\":[";
    for(int i=0;i<6;++i){
        if(i)json+=",";
        const auto& p=result.preprocessingProfile[i];
        json+="{\"index\":"+std::to_string(i)+",\"attempted_mask\":"+std::to_string(p.attemptedMask);
        const char* names[]={"warp_us","gray_contrast_us","visibility_us","blur_us","coordinates_us","features_us"};
        for(int j=0;j<6;++j)json+=",\""+std::string(names[j])+"\":"+std::to_string(p.us[j]);
        json+="}";
    }
    json += "]}";
    httpd_resp_set_type(req,"application/json");
    httpd_resp_set_hdr(req,"Cache-Control","no-store");
    return httpd_resp_send(req,json.c_str(),json.size());
}

static MeterOtaHealth::Evidence observeOtaHealth()
{
    portENTER_CRITICAL(&polarTestMux);
    const auto test=polarTestResult;
    const bool testActive=polarTestActive;
    portEXIT_CRITICAL(&polarTestMux);
    bool modelPassed=!testActive && test.completed==6 &&
        std::string(test.status)=="all_output_bytes_match";
    for(int i=0;i<6;++i)modelPassed=modelPassed && test.differingBytes[i]==0;
    const auto cycle=CycleTelemetry::snapshot();
    const int faults=getSystemStatus();
    MeterOtaHealth::Evidence evidence;
#ifdef CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE
    evidence.rollbackConfigured=true;
#endif
    esp_ota_img_states_t imageState=ESP_OTA_IMG_UNDEFINED;
    const auto* running=esp_ota_get_running_partition();
    const bool stateKnown=running && esp_ota_get_state_partition(running,&imageState)==ESP_OK;
    evidence.pendingImage=stateKnown && imageState==ESP_OTA_IMG_PENDING_VERIFY;
    evidence.bundleVerified=MeterBundle::bootSelection().state()==MeterBundle::SelectionState::Selected;
    evidence.configurationReadable=ConfigStorage::safe().load();
    evidence.modelSelfTestPassed=modelPassed;
    evidence.processingActive=cycle.active || testActive;
    evidence.systemFaults=static_cast<uint32_t>(faults);
    evidence.consecutiveReaderCycles=cycle.acceptedReaderStreak;
    evidence.lastPipelineCompleted=cycle.last.pipelineCompleted;
    evidence.lastReaderAccepted=cycle.last.readerAccepted;
    evidence.nowUs=esp_timer_get_time();
    evidence.startedUs=cycle.last.startedUs;
    evidence.capturedUs=cycle.last.capturedUs;
    evidence.finishedUs=cycle.last.finishedUs;
    return evidence;
}

// Worker-only operation. Never called from boot observation or a GET handler.
// Locks precede fresh evidence; SDK write failure/readback uncertainty is not retried.
const char* acceptHealthyManagedImage()
{
    ProcessingAccess processing;if(!processing)return "processing_busy";
    UpdateAccess update;if(!update)return "update_busy";
    const auto evidence=observeOtaHealth();
    const char* reason=MeterOtaHealth::evaluate(evidence);
    if(std::string(reason)!="ready")return reason;
    const auto* running=esp_ota_get_running_partition();
    esp_ota_img_states_t state=ESP_OTA_IMG_UNDEFINED;
    if(!running || esp_ota_get_state_partition(running,&state)!=ESP_OK ||
        state!=ESP_OTA_IMG_PENDING_VERIFY)return "pending_state_changed";
    if(esp_ota_mark_app_valid_cancel_rollback()!=ESP_OK)return "acceptance_write_failed";
    if(esp_ota_get_running_partition()!=running ||
        esp_ota_get_state_partition(running,&state)!=ESP_OK || state!=ESP_OTA_IMG_VALID)
        return "acceptance_readback_uncertain";
    return "accepted";
}

// Only the automatic-flow task calls this, after initialization and between
// cycles. A failed write/readback is terminal for this boot, never retried.
static void servicePendingImage()
{
    static bool terminal=false;
    static int64_t firstCheckUs=0;
    if(terminal)return;
    const auto evidence=observeOtaHealth();
    if(!evidence.rollbackConfigured || !evidence.pendingImage){terminal=true;return;}
    if(!firstCheckUs)firstCheckUs=esp_timer_get_time();
    if(esp_timer_get_time()-firstCheckUs>600000000){
        terminal=true;
        LogFile.WriteToFile(ESP_LOG_ERROR,TAG,"OTA validation window expired; image remains unaccepted");
        return;
    }
    if(!evidence.bundleVerified || evidence.systemFaults || !evidence.configurationReadable)return;
    if(!evidence.modelSelfTestPassed){
        portENTER_CRITICAL(&polarTestMux);
        const bool busy=polarTestActive;
        if(!busy){polarTestActive=true;polarTestResult=PolarRuntimeTestResult{};}
        portEXIT_CRITICAL(&polarTestMux);
        if(busy)return;
        const auto result=runPolarRuntimeTest();
        portENTER_CRITICAL(&polarTestMux);
        polarTestResult=result;polarTestActive=false;
        portEXIT_CRITICAL(&polarTestMux);
        if(std::string(result.status)=="processing_busy")return;
        const auto tested=observeOtaHealth();
        if(!tested.modelSelfTestPassed){
            terminal=true;
            LogFile.WriteToFile(ESP_LOG_ERROR,TAG,"OTA model self-test failed; image remains unaccepted");
        }
        return;
    }
    if(std::string(MeterOtaHealth::evaluate(evidence))!="ready")return;
    const char* outcome=acceptHealthyManagedImage();
    if(std::string(outcome)=="processing_busy" || std::string(outcome)=="update_busy")return;
    terminal=true;
    LogFile.WriteToFile(std::string(outcome)=="accepted"?ESP_LOG_INFO:ESP_LOG_ERROR,
        TAG,std::string("OTA acceptance outcome: ")+outcome);
}

esp_err_t handler_ota_health(httpd_req_t* req)
{
    const auto evidence=observeOtaHealth();
    const bool modelPassed=evidence.modelSelfTestPassed;
    const int faults=static_cast<int>(evidence.systemFaults);
    const bool completedCapture=!evidence.processingActive && evidence.lastPipelineCompleted &&
        evidence.capturedUs>0 && evidence.finishedUs>=evidence.capturedUs;
    esp_ota_img_states_t state=ESP_OTA_IMG_UNDEFINED;
    const auto* running=esp_ota_get_running_partition();
    const bool stateKnown=running && esp_ota_get_state_partition(running,&state)==ESP_OK;
    const char* reason=MeterOtaHealth::evaluate(evidence);
    // Observational snapshots only. This endpoint holds no transaction lock and
    // does not prove the installed bootloader's rollback/recovery behavior.
    std::string json="{\"version\":2,\"system_faults\":"+std::to_string(faults)+
        ",\"configuration_readable\":"+(evidence.configurationReadable?"true":"false")+
        ",\"frozen_model_self_test_passed\":"+(modelPassed?"true":"false")+
        ",\"last_capture_pipeline_completed\":"+(completedCapture?"true":"false")+
        ",\"bundle_compatibility_verified\":"+(evidence.bundleVerified?"true":"false")+
        ",\"rollback_configured\":"+(evidence.rollbackConfigured?"true":"false")+
        ",\"image_state_known\":"+(stateKnown?"true":"false")+
        ",\"pending_image\":"+(evidence.pendingImage?"true":"false")+
        ",\"consecutive_reader_cycles\":"+std::to_string(evidence.consecutiveReaderCycles)+
        ",\"software_policy_ready\":"+(std::string(reason)=="ready"?"true":"false")+
        ",\"software_policy_reason\":\""+reason+"\",\"rollback_verified\":false,"
        "\"acceptance_ready\":false,\"image_accepted_by_this_request\":false}";
    httpd_resp_set_type(req,"application/json");
    httpd_resp_set_hdr(req,"Cache-Control","no-store");
    return httpd_resp_send(req,json.c_str(),json.size());
}

esp_err_t handler_get_heap(httpd_req_t *req)
{
#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_get_heap - Start");
    ESP_LOGD(TAG, "handler_get_heap uri: %s", req->uri);
#endif

    std::string zw = "Heap info:<br>" + getESPHeapInfo();

#ifdef TASK_ANALYSIS_ON
    char *pcTaskList = (char *)calloc_psram_heap(std::string(TAG) + "->pcTaskList", 1, sizeof(char) * 768, MALLOC_CAP_8BIT | MALLOC_CAP_SPIRAM);
    if (pcTaskList)
    {
        vTaskList(pcTaskList);
        zw = zw + "<br><br>Task info:<br><pre>Name | State | Prio | Lowest stacksize | Creation order | CPU (-1=NoAffinity)<br>" + std::string(pcTaskList) + "</pre>";
        free_psram_heap(std::string(TAG) + "->pcTaskList", pcTaskList);
    }
    else
    {
        zw = zw + "<br><br>Task info:<br>ERROR - Allocation of TaskList buffer in PSRAM failed";
    }
#endif

    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");

    if (zw.length() > 0)
    {
        httpd_resp_send(req, zw.c_str(), zw.length());
    }
    else
    {
        httpd_resp_send(req, NULL, 0);
    }

#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_get_heap - Done");
#endif

    return ESP_OK;
}

esp_err_t handler_init(httpd_req_t *req)
{
#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_init - Start");
    ESP_LOGD(TAG, "handler_doinit uri: %s", req->uri);
#endif

    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    const char *resp_str = "Init started<br>";
    httpd_resp_send(req, resp_str, HTTPD_RESP_USE_STRLEN);

    doInit();

    resp_str = "Init done<br>";
    httpd_resp_send(req, resp_str, HTTPD_RESP_USE_STRLEN);

#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_init - Done");
#endif

    return ESP_OK;
}

static std::atomic_flag streamActive = ATOMIC_FLAG_INIT;
struct StreamRequest { httpd_req_t* request; bool light; };

static void streamWorker(void* argument)
{
    StreamRequest* work = static_cast<StreamRequest*>(argument);
    httpd_req_t* request = work->request;
    const httpd_handle_t server = request->handle;
    const int socket = httpd_req_to_sockfd(request);
    Camera.CaptureToStream(request, work->light);
    delete work;
    // Multipart streams end by closing the connection, never by reusing it.
    httpd_req_async_handler_complete(request);
    httpd_sess_trigger_close(server, socket);
    streamActive.clear();
    vTaskDelete(nullptr);
}

esp_err_t handler_stream(httpd_req_t *req)
{
    char query[64];
    char value[10];
    bool light = false;
    if (httpd_req_get_url_query_len(req))
    {
        if (httpd_req_get_url_query_str(req, query, sizeof(query)) != ESP_OK)
            return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid stream query");
        const esp_err_t parsed = httpd_query_key_value(query, "flashlight", value, sizeof(value));
        if (parsed != ESP_OK && parsed != ESP_ERR_NOT_FOUND)
            return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "Invalid flashlight value");
        if (parsed == ESP_OK)
        {
            if (!strcmp(value, "true") || !strcmp(value, "1")) light = true;
            else if (strcmp(value, "false") && strcmp(value, "0"))
                return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "flashlight must be true or false");
        }
    }
    if (!Camera.getCameraInitSuccessful())
        return cameraUnavailableResponse(req);
    if (streamActive.test_and_set()) return cameraBusyResponse(req);
    StreamPreview::reset();
    StreamRequest* work = new (std::nothrow) StreamRequest{nullptr, light};
    if (!work) { streamActive.clear(); return cameraBusyResponse(req); }
    esp_err_t result = httpd_req_async_handler_begin(req, &work->request);
    if (result != ESP_OK)
    {
        delete work;
        streamActive.clear();
        return result;
    }
    if (xTaskCreate(streamWorker, "camera_stream", 6144, work, 3, nullptr) != pdPASS)
    {
        // The copied request must be completed even when no worker can start.
        cameraBusyResponse(work->request);
        httpd_req_async_handler_complete(work->request);
        delete work;
        streamActive.clear();
    }
    return ESP_OK;
}

esp_err_t handler_flow_start(httpd_req_t *req)
{
    if (!Camera.getCameraInitSuccessful()) return cameraUnavailableResponse(req);
#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_flow_start - Start");
#endif

    ESP_LOGD(TAG, "handler_flow_start uri: %s", req->uri);

    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");

    if (autostartIsEnabled && xHandletask_autodoFlow)
    {
        xTaskAbortDelay(xHandletask_autodoFlow); // Delay will be aborted if task is in blocked (waiting) state. If task is already running, no action
        LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "Flow start triggered by REST API /flow_start");
        const char *resp_str = "The flow is going to be started immediately or is already running";
        httpd_resp_send(req, resp_str, HTTPD_RESP_USE_STRLEN);
    }
    else
    {
        LogFile.WriteToFile(ESP_LOG_WARN, TAG, "Flow start triggered by REST API, but flow is not active!");
        httpd_resp_send_err(req, HTTPD_403_FORBIDDEN, "Flow start triggered by REST API, but flow is not active");
    }

#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_flow_start - Done");
#endif

    return ESP_OK;
}

#ifdef ENABLE_MQTT
esp_err_t MQTTCtrlFlowStart(std::string _topic)
{
#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("MQTTCtrlFlowStart - Start");
#endif

    ESP_LOGD(TAG, "MQTTCtrlFlowStart: topic %s", _topic.c_str());

    if (autostartIsEnabled)
    {
        xTaskAbortDelay(xHandletask_autodoFlow); // Delay will be aborted if task is in blocked (waiting) state. If task is already running, no action
        LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "Flow start triggered by MQTT topic " + _topic);
    }
    else
    {
        LogFile.WriteToFile(ESP_LOG_WARN, TAG, "Flow start triggered by MQTT topic " + _topic + ", but flow is not active!");
    }

#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("MQTTCtrlFlowStart - Done");
#endif

    return ESP_OK;
}
#endif // ENABLE_MQTT

esp_err_t handler_json(httpd_req_t *req)
{
#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_json - Start");
#endif

    ESP_LOGD(TAG, "handler_JSON uri: %s", req->uri);

    if (bTaskAutoFlowCreated)
    {
        httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
        httpd_resp_set_type(req, "application/json");

        std::string zw = flowctrl.getJSON();
        if (zw.length() > 0)
        {
            httpd_resp_send(req, zw.c_str(), zw.length());
        }
        else
        {
            httpd_resp_send(req, NULL, 0);
        }
    }
    else
    {
        httpd_resp_send_err(req, HTTPD_403_FORBIDDEN, "Flow not (yet) started: REST API /json not yet available!");
        return ESP_ERR_NOT_FOUND;
    }

#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_JSON - Done");
#endif

    return ESP_OK;
}

/**
 * Generates a http response containing the OpenMetrics (https://openmetrics.io/) text wire format 
 * according to https://github.com/OpenObservability/OpenMetrics/blob/main/specification/OpenMetrics.md#text-format.
 * 
 * A MetricFamily with a Metric for each Sequence is provided. If no valid value is available, the metric is not provided.
 * MetricPoints are provided without a timestamp. Additional metrics with some device information is also provided.
 * 
 * The metric name prefix is 'ai_on_the_edge_device_'.
 * 
 * example configuration for Prometheus (`prometheus.yml`):
 * 
 *    - job_name: watermeter
 *      static_configs:
 *        - targets: ['watermeter.fritz.box']
 * 
*/
esp_err_t handler_openmetrics(httpd_req_t *req)
{
#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_openmetrics - Start");
#endif

    ESP_LOGD(TAG, "handler_openmetrics uri: %s", req->uri);

    if (bTaskAutoFlowCreated)
    {
        httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
        httpd_resp_set_type(req, "text/plain"); // application/openmetrics-text is not yet supported by prometheus so we use text/plain for now

        const string metricNamePrefix = "ai_on_the_edge_device";

        // get current measurement (flow)
        string response = createSequenceMetrics(metricNamePrefix, flowctrl.getNumbers());

        // CPU Temperature
        response += createMetric(metricNamePrefix + "_cpu_temperature_celsius", "current cpu temperature in celsius", "gauge", std::to_string((int)temperatureRead())); 

        // WiFi signal strength
        response += createMetric(metricNamePrefix + "_rssi_dbm", "current WiFi signal strength in dBm", "gauge", std::to_string(get_WIFI_RSSI())); 

        // memory info
        response += createMetric(metricNamePrefix + "_memory_heap_free_bytes", "available heap memory", "gauge", std::to_string(getESPHeapSize())); 

        // device uptime
        response += createMetric(metricNamePrefix + "_uptime_seconds", "device uptime in seconds", "gauge", std::to_string((long)getUpTime())); 

        // data aquisition round
        response += createMetric(metricNamePrefix + "_rounds_total", "data aquisition rounds since device startup", "counter", std::to_string(countRounds));

        // the response always contains at least the metadata (HELP, TYPE) for the MetricFamily so no length check is needed
        httpd_resp_send(req, response.c_str(), response.length());
    }
    else
    {
        httpd_resp_send_err(req, HTTPD_403_FORBIDDEN, "Flow not (yet) started: REST API /metrics not yet available!");
        return ESP_ERR_NOT_FOUND;
    }

#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_openmetrics - Done");
#endif

    return ESP_OK;
}

esp_err_t handler_wasserzaehler(httpd_req_t *req)
{
#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler water counter - Start");
#endif

    if (bTaskAutoFlowCreated)
    {
        bool _rawValue = false;
        bool _noerror = false;
        bool _all = false;
        std::string _type = "value";
        std::string zw;

        ESP_LOGD(TAG, "handler water counter uri: %s", req->uri);

        char _query[100];
        char _size[10];

        if (httpd_req_get_url_query_str(req, _query, 100) == ESP_OK)
        {
            //        ESP_LOGD(TAG, "Query: %s", _query);
            if (httpd_query_key_value(_query, "all", _size, 10) == ESP_OK)
            {
#ifdef DEBUG_DETAIL_ON
                ESP_LOGD(TAG, "all is found%s", _size);
#endif
                _all = true;
            }

            if (httpd_query_key_value(_query, "type", _size, 10) == ESP_OK)
            {
#ifdef DEBUG_DETAIL_ON
                ESP_LOGD(TAG, "all is found: %s", _size);
#endif
                _type = std::string(_size);
            }

            if (httpd_query_key_value(_query, "rawvalue", _size, 10) == ESP_OK)
            {
#ifdef DEBUG_DETAIL_ON
                ESP_LOGD(TAG, "rawvalue is found: %s", _size);
#endif
                _rawValue = true;
            }

            if (httpd_query_key_value(_query, "noerror", _size, 10) == ESP_OK)
            {
#ifdef DEBUG_DETAIL_ON
                ESP_LOGD(TAG, "noerror is found: %s", _size);
#endif
                _noerror = true;
            }
        }

        httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");

        if (_all)
        {
            httpd_resp_set_type(req, "text/plain");
            ESP_LOGD(TAG, "TYPE: %s", _type.c_str());
            int _intype = READOUT_TYPE_VALUE;

            if (_type == "prevalue")
            {
                _intype = READOUT_TYPE_PREVALUE;
            }

            if (_type == "raw")
            {
                _intype = READOUT_TYPE_RAWVALUE;
            }

            if (_type == "error")
            {
                _intype = READOUT_TYPE_ERROR;
            }

            zw = flowctrl.getReadoutAll(_intype);
            ESP_LOGD(TAG, "ZW: %s", zw.c_str());

            if (zw.length() > 0)
            {
                httpd_resp_send(req, zw.c_str(), zw.length());
            }

            return ESP_OK;
        }

        std::string *status = flowctrl.getActStatus();
        std::string query = std::string(_query);
        //    ESP_LOGD(TAG, "Query: %s, query.c_str());

        if (query.find("full") != std::string::npos)
        {
            std::string txt;
            txt = "<body style=\"font-family: arial\">";

            if ((countRounds <= 1) && (*status != std::string("Flow finished")))
            {
                // First round not completed yet
                txt += "<h3>Please wait for the first round to complete!</h3><h3>Current state: " + *status + "</h3>\n";
            }
            else
            {
                txt += "<h3>Value</h3>";
            }

            httpd_resp_sendstr_chunk(req, txt.c_str());
        }

        zw = flowctrl.getReadout(_rawValue, _noerror, 0);

        if (zw.length() > 0)
        {
            httpd_resp_sendstr_chunk(req, zw.c_str());
        }

        if (query.find("full") != std::string::npos)
        {
            std::string txt, zw;

            if ((countRounds <= 1) && (*status != std::string("Flow finished")))
            {
                // First round not completed yet
                // Nothing to do
            }
            else
            {
                /* Digit ROIs */
                txt = "<body style=\"font-family: arial\">";
                txt += "<hr><h3>Recognized Digit ROIs (previous round)</h3>\n";
                txt += "<table style=\"border-spacing: 5px\"><tr style=\"text-align: center; vertical-align: top;\">\n";

                std::vector<HTMLInfo *> htmlinfodig;
                htmlinfodig = flowctrl.GetAllDigit();

                for (int i = 0; i < htmlinfodig.size(); ++i)
                {
                    if (flowctrl.GetTypeDigit() == Digit)
                    {
                        // Numbers greater than 10 and less than 0 indicate NaN, since a Roi can only have values ​​from 0 to 9.
                        if ((htmlinfodig[i]->val >= 10) || (htmlinfodig[i]->val < 0))
                        {
                            zw = "NaN";
                        }
                        else
                        {
                            zw = std::to_string((int)htmlinfodig[i]->val);
                        }

                        txt += "<td style=\"width: 100px\"><h4>" + zw + "</h4><p><img src=\"/img_tmp/" + htmlinfodig[i]->filename + "\"></p></td>\n";
                    }
                    else
                    {
                        std::stringstream stream;
                        stream << std::fixed << std::setprecision(1) << htmlinfodig[i]->val;
                        zw = stream.str();

                        // Numbers greater than 10 and less than 0 indicate NaN, since a Roi can only have values ​​from 0 to 9.
                        if ((std::stod(zw) >= 10) || (std::stod(zw) < 0))
                        {
                            zw = "NaN";
                        }

                        txt += "<td style=\"width: 100px\"><h4>" + zw + "</h4><p><img src=\"/img_tmp/" + htmlinfodig[i]->filename + "\"></p></td>\n";
                    }
                    delete htmlinfodig[i];
                }

                htmlinfodig.clear();

                txt += "</tr></table>\n";
                httpd_resp_sendstr_chunk(req, txt.c_str());

                /* Analog ROIs */
                txt = "<hr><h3>Recognized Analog ROIs (previous round)</h3>\n";
                txt += "<table style=\"border-spacing: 5px\"><tr style=\"text-align: center; vertical-align: top;\">\n";

                std::vector<HTMLInfo *> htmlinfoana;
                htmlinfoana = flowctrl.GetAllAnalog();

                for (int i = 0; i < htmlinfoana.size(); ++i)
                {
                    std::stringstream stream;
                    stream << std::fixed << std::setprecision(1) << htmlinfoana[i]->val;
                    zw = stream.str();
                    
                    // Numbers greater than 10 and less than 0 indicate NaN, since a Roi can only have values ​​from 0 to 9.
                    if ((std::stod(zw) >= 10) || (std::stod(zw) < 0))
                    {
                        zw = "NaN";
                    }

                    txt += "<td style=\"width: 150px;\"><h4>" + zw + "</h4><p><img src=\"/img_tmp/" + htmlinfoana[i]->filename + "\"></p></td>\n";
                    delete htmlinfoana[i];
                }

                htmlinfoana.clear();

                txt += "</tr>\n</table>\n";
                httpd_resp_sendstr_chunk(req, txt.c_str());

                /* Full Image
                 * Only show it after the image got taken */
                txt = "<hr><h3>Full Image (current round)</h3>\n";

                if ((*status == std::string("Initialization")) ||
                    (*status == std::string("Initialization (delayed)")) ||
                    (*status == std::string("Take Image")))
                {
                    txt += "<p>Current state: " + *status + "</p>\n";
                }
                else
                {
                    txt += "<img src=\"/img_tmp/alg_roi.jpg\">\n";
                }
                httpd_resp_sendstr_chunk(req, txt.c_str());
            }
        }

        /* Respond with an empty chunk to signal HTTP response completion */
        httpd_resp_sendstr_chunk(req, NULL);
    }
    else
    {
        httpd_resp_send_err(req, HTTPD_403_FORBIDDEN, "Flow not (yet) started: REST API /value not available!");
        return ESP_ERR_NOT_FOUND;
    }

#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_wasserzaehler - Done");
#endif

    return ESP_OK;
}

esp_err_t handler_editflow(httpd_req_t *req)
{
    CameraAccess access;
    if (!access) return cameraBusyResponse(req);
#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_editflow - Start");
#endif

    ESP_LOGD(TAG, "handler_editflow uri: %s", req->uri);

    char _query[512];
    char _valuechar[30];
    std::string _task;

    if (httpd_req_get_url_query_str(req, _query, 512) == ESP_OK)
    {
        if (httpd_query_key_value(_query, "task", _valuechar, 30) == ESP_OK)
        {
#ifdef DEBUG_DETAIL_ON
            ESP_LOGD(TAG, "task is found: %s", _valuechar);
#endif
            _task = std::string(_valuechar);
        }
    }

    if (_task.compare("namenumbers") == 0)
    {
        ESP_LOGD(TAG, "Get NUMBER list");
        return get_numbers_file_handler(req);
    }

    if (_task.compare("data") == 0)
    {
        ESP_LOGD(TAG, "Get data list");
        return get_data_file_handler(req);
    }

    if (_task.compare("tflite") == 0)
    {
        ESP_LOGD(TAG, "Get tflite list");
        return get_tflite_file_handler(req);
    }

    if (_task.compare("copy") == 0)
    {
        std::string in, out, zw;

        httpd_query_key_value(_query, "in", _valuechar, 30);
        in = std::string(_valuechar);
        httpd_query_key_value(_query, "out", _valuechar, 30);
        out = std::string(_valuechar);

#ifdef DEBUG_DETAIL_ON
        ESP_LOGD(TAG, "in: %s", in.c_str());
        ESP_LOGD(TAG, "out: %s", out.c_str());
#endif

        in = "/sdcard" + in;
        out = "/sdcard" + out;

        CopyFile(in, out);
        zw = "Copy Done";
        httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
        httpd_resp_send(req, zw.c_str(), zw.length());
    }

    if (_task.compare("cutref") == 0)
    {
        std::string in, out, zw;
        int x = 0, y = 0, dx = 20, dy = 20;
        bool enhance = false;

        httpd_query_key_value(_query, "in", _valuechar, 30);
        in = std::string(_valuechar);

        httpd_query_key_value(_query, "out", _valuechar, 30);
        out = std::string(_valuechar);

        httpd_query_key_value(_query, "x", _valuechar, 30);
        std::string _x = std::string(_valuechar);
        if (isStringNumeric(_x))
        {
            x = std::stoi(_x);
        }

        httpd_query_key_value(_query, "y", _valuechar, 30);
        std::string _y = std::string(_valuechar);
        if (isStringNumeric(_y))
        {
            y = std::stoi(_y);
        }

        httpd_query_key_value(_query, "dx", _valuechar, 30);
        std::string _dx = std::string(_valuechar);
        if (isStringNumeric(_dx))
        {
            dx = std::stoi(_dx);
        }

        httpd_query_key_value(_query, "dy", _valuechar, 30);
        std::string _dy = std::string(_valuechar);
        if (isStringNumeric(_dy))
        {
            dy = std::stoi(_dy);
        }

#ifdef DEBUG_DETAIL_ON
        ESP_LOGD(TAG, "in: %s", in.c_str());
        ESP_LOGD(TAG, "out: %s", out.c_str());
        ESP_LOGD(TAG, "x: %s", _x.c_str());
        ESP_LOGD(TAG, "y: %s", _y.c_str());
        ESP_LOGD(TAG, "dx: %s", _dx.c_str());
        ESP_LOGD(TAG, "dy: %s", _dy.c_str());
#endif

        if (httpd_query_key_value(_query, "enhance", _valuechar, 10) == ESP_OK)
        {
            string _enhance = std::string(_valuechar);

            if (_enhance.compare("true") == 0)
            {
                enhance = true;
            }
        }

        in = "/sdcard" + in;
        out = "/sdcard" + out;

        std::string out2 = out.substr(0, out.length() - 4) + "_org.jpg";

        if ((flowctrl.SetupModeActive || (*flowctrl.getActStatus() == std::string("Flow finished"))) && psram_init_shared_memory_for_take_image_step())
        {
            LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Taking image for Alignment Mark Update...");

            CAlignAndCutImage *caic = new CAlignAndCutImage("cutref", in);
            caic->CutAndSave(out2, x, y, dx, dy);
            delete caic;

            CImageBasis *cim = new CImageBasis("cutref", out2);

            if (enhance)
            {
                cim->Contrast(90);
            }

            cim->SaveToFile(out);
            delete cim;

            psram_deinit_shared_memory_for_take_image_step();
            zw = "CutImage Done";
        }
        else
        {
            LogFile.WriteToFile(ESP_LOG_WARN, TAG, std::string("Taking image for Alignment Mark not possible while device") + " is busy with a round (Current State: '" + *flowctrl.getActStatus() + "')!");
            zw = "Device Busy";
        }

        httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
        httpd_resp_send(req, zw.c_str(), zw.length());
    }

    // wird beim Erstellen eines neuen Referenzbildes aufgerufen
    std::string *sys_status = flowctrl.getActStatus();

    if ((sys_status->c_str() != std::string("Take Image")) && (sys_status->c_str() != std::string("Aligning")))
    {
        if ((_task.compare("test_take") == 0) || (_task.compare("cam_settings") == 0))
        {
            std::string _host = "";

            // laden der aktuellen Kameraeinstellungen(CCstatus) in den Zwischenspeicher(CFstatus)
            setCCstatusToCFstatus(); // CCstatus >>> CFstatus

            if (httpd_query_key_value(_query, "host", _valuechar, 30) == ESP_OK)
            {
                _host = std::string(_valuechar);
            }

            if (httpd_query_key_value(_query, "waitb", _valuechar, 30) == ESP_OK)
            {
                std::string _waitb = std::string(_valuechar);
                if (isStringNumeric(_waitb))
                {
                    CFstatus.WaitBeforePicture = std::stoi(_valuechar);
                }
            }

            if (httpd_query_key_value(_query, "aecgc", _valuechar, 30) == ESP_OK)
            {
                std::string _aecgc = std::string(_valuechar);
                if (isStringNumeric(_aecgc))
                {
                    int _aecgc_ = std::stoi(_valuechar);
                    switch (_aecgc_)
                    {
                        case 1:
                            CFstatus.ImageGainceiling = GAINCEILING_4X; 
                            break;
                        case 2:
                            CFstatus.ImageGainceiling = GAINCEILING_8X; 
                            break;
                        case 3:
                            CFstatus.ImageGainceiling = GAINCEILING_16X; 
                            break;
                        case 4:
                            CFstatus.ImageGainceiling = GAINCEILING_32X; 
                            break;
                        case 5:
                            CFstatus.ImageGainceiling = GAINCEILING_64X; 
                            break;
                        case 6:
                            CFstatus.ImageGainceiling = GAINCEILING_128X; 
                            break;
                        default:
                            CFstatus.ImageGainceiling = GAINCEILING_2X;
                    }
                }
                else
                {
                    if (_aecgc == "X4") {
                        CFstatus.ImageGainceiling = GAINCEILING_4X;
                    }
                    else if (_aecgc == "X8") {
                        CFstatus.ImageGainceiling = GAINCEILING_8X;
                    }
                    else if (_aecgc == "X16") {
                        CFstatus.ImageGainceiling = GAINCEILING_16X;
                    }
                    else if (_aecgc == "X32") {
                        CFstatus.ImageGainceiling = GAINCEILING_32X;
                    }
                    else if (_aecgc == "X64") {
                        CFstatus.ImageGainceiling = GAINCEILING_64X;
                    }
                    else if (_aecgc == "X128") {
                        CFstatus.ImageGainceiling = GAINCEILING_128X;
                    }
                    else {
                        CFstatus.ImageGainceiling = GAINCEILING_2X;
                    }
                }
            }

            if (httpd_query_key_value(_query, "qual", _valuechar, 30) == ESP_OK)
            {
                std::string _qual = std::string(_valuechar);
                if (isStringNumeric(_qual))
                {
                    int _qual_ = std::stoi(_valuechar);
                    CFstatus.ImageQuality = clipInt(_qual_, 63, 6);
                }
            }

            if (httpd_query_key_value(_query, "bri", _valuechar, 30) == ESP_OK)
            {
                std::string _bri = std::string(_valuechar);
                if (isStringNumeric(_bri))
                {
                    int _bri_ = std::stoi(_valuechar);
                    CFstatus.ImageBrightness = clipInt(_bri_, 2, -2);
                }
            }

            if (httpd_query_key_value(_query, "con", _valuechar, 30) == ESP_OK)
            {
                std::string _con = std::string(_valuechar);
                if (isStringNumeric(_con))
                {
                    int _con_ = std::stoi(_valuechar);
                    CFstatus.ImageContrast = clipInt(_con_, 2, -2);
                }
            }

            if (httpd_query_key_value(_query, "sat", _valuechar, 30) == ESP_OK)
            {
                std::string _sat = std::string(_valuechar);
                if (isStringNumeric(_sat))
                {
                    int _sat_ = std::stoi(_valuechar);
                    CFstatus.ImageSaturation = clipInt(_sat_, 2, -2);
                }
            }

            if (httpd_query_key_value(_query, "shp", _valuechar, 30) == ESP_OK)
            {
                std::string _shp = std::string(_valuechar);
                if (isStringNumeric(_shp))
                {
                    int _shp_ = std::stoi(_valuechar);
                    if (CCstatus.CamSensor_id == OV2640_PID)
                    {
                        CFstatus.ImageSharpness = clipInt(_shp_, 2, -2);
                    }
                    else
                    {
                        CFstatus.ImageSharpness = clipInt(_shp_, 3, -3);
                    }
                }
            }

            if (httpd_query_key_value(_query, "ashp", _valuechar, 30) == ESP_OK)
            {
                std::string _ashp = std::string(_valuechar);
                CFstatus.ImageAutoSharpness = alphanumericToBoolean(_ashp);
            }

            if (httpd_query_key_value(_query, "spe", _valuechar, 30) == ESP_OK)
            {
                std::string _spe = std::string(_valuechar);
                if (isStringNumeric(_spe))
                {
                    int _spe_ = std::stoi(_valuechar);
                    CFstatus.ImageSpecialEffect = clipInt(_spe_, 6, 0);
                }
                else
                {
                    if (_spe == "negative") {
                        CFstatus.ImageSpecialEffect = 1;
                    }
                    else if (_spe == "grayscale") {
                        CFstatus.ImageSpecialEffect = 2;
                    }
                    else if (_spe == "red") {
                        CFstatus.ImageSpecialEffect = 3;
                    }
                    else if (_spe == "green") {
                        CFstatus.ImageSpecialEffect = 4;
                    }
                    else if (_spe == "blue") {
                        CFstatus.ImageSpecialEffect = 5;
                    }
                    else if (_spe == "retro") {
                        CFstatus.ImageSpecialEffect = 6;
                    }
                    else {
                        CFstatus.ImageSpecialEffect = 0;
                    }
                }
            }

            if (httpd_query_key_value(_query, "wbm", _valuechar, 30) == ESP_OK)
            {
                std::string _wbm = std::string(_valuechar);
                if (isStringNumeric(_wbm))
                {
                    int _wbm_ = std::stoi(_valuechar);
                    CFstatus.ImageWbMode = clipInt(_wbm_, 4, 0);
                }
                else
                {
                    if (_wbm == "sunny") {
                        CFstatus.ImageWbMode = 1;
                    }
                    else if (_wbm == "cloudy") {
                        CFstatus.ImageWbMode = 2;
                    }
                    else if (_wbm == "office") {
                        CFstatus.ImageWbMode = 3;
                    }
                    else if (_wbm == "home") {
                        CFstatus.ImageWbMode = 4;
                    }
                    else {
                        CFstatus.ImageWbMode = 0;
                    }
                }
            }

            if (httpd_query_key_value(_query, "awb", _valuechar, 30) == ESP_OK)
            {
                std::string _awb = std::string(_valuechar);
                CFstatus.ImageAwb = alphanumericToBoolean(_awb);
            }

            if (httpd_query_key_value(_query, "awbg", _valuechar, 30) == ESP_OK)
            {
                std::string _awbg = std::string(_valuechar);
                CFstatus.ImageAwbGain = alphanumericToBoolean(_awbg);
            }

            if (httpd_query_key_value(_query, "aec", _valuechar, 30) == ESP_OK)
            {
                std::string _aec = std::string(_valuechar);
                CFstatus.ImageAec = alphanumericToBoolean(_aec);
            }

            if (httpd_query_key_value(_query, "aec2", _valuechar, 30) == ESP_OK)
            {
                std::string _aec2 = std::string(_valuechar);
                CFstatus.ImageAec2 = alphanumericToBoolean(_aec2);
            }

            if (httpd_query_key_value(_query, "ael", _valuechar, 30) == ESP_OK)
            {
                std::string _ael = std::string(_valuechar);
                if (isStringNumeric(_ael))
                {
                    int _ael_ = std::stoi(_valuechar);
                    if (CCstatus.CamSensor_id == OV2640_PID)
                    {
                        CFstatus.ImageAeLevel = clipInt(_ael_, 2, -2);
                    }
                    else
                    {
                        CFstatus.ImageAeLevel = clipInt(_ael_, 5, -5);
                    }
                }
            }

            if (httpd_query_key_value(_query, "aecv", _valuechar, 30) == ESP_OK)
            {
                std::string _aecv = std::string(_valuechar);
                if (isStringNumeric(_aecv))
                {
                    int _aecv_ = std::stoi(_valuechar);
                    CFstatus.ImageAecValue = clipInt(_aecv_, 1200, 0);
                }
            }

            if (httpd_query_key_value(_query, "agc", _valuechar, 30) == ESP_OK)
            {
                std::string _agc = std::string(_valuechar);
                CFstatus.ImageAgc = alphanumericToBoolean(_agc);
            }

            if (httpd_query_key_value(_query, "agcg", _valuechar, 30) == ESP_OK)
            {
                std::string _agcg = std::string(_valuechar);
                if (isStringNumeric(_agcg))
                {
                    int _agcg_ = std::stoi(_valuechar);
                    CFstatus.ImageAgcGain = clipInt(_agcg_, 30, 0);
                }
            }

            if (httpd_query_key_value(_query, "bpc", _valuechar, 30) == ESP_OK)
            {
                std::string _bpc = std::string(_valuechar);
                CFstatus.ImageBpc = alphanumericToBoolean(_bpc);
            }

            if (httpd_query_key_value(_query, "wpc", _valuechar, 30) == ESP_OK)
            {
                std::string _wpc = std::string(_valuechar);
                CFstatus.ImageWpc = alphanumericToBoolean(_wpc);
            }

            if (httpd_query_key_value(_query, "rgma", _valuechar, 30) == ESP_OK)
            {
                std::string _rgma = std::string(_valuechar);
                CFstatus.ImageRawGma = alphanumericToBoolean(_rgma);
            }

            if (httpd_query_key_value(_query, "lenc", _valuechar, 30) == ESP_OK)
            {
                std::string _lenc = std::string(_valuechar);
                CFstatus.ImageLenc = alphanumericToBoolean(_lenc);
            }

            if (httpd_query_key_value(_query, "mirror", _valuechar, 30) == ESP_OK)
            {
                std::string _mirror = std::string(_valuechar);
                CFstatus.ImageHmirror = alphanumericToBoolean(_mirror);
            }

            if (httpd_query_key_value(_query, "flip", _valuechar, 30) == ESP_OK)
            {
                std::string _flip = std::string(_valuechar);
                CFstatus.ImageVflip = alphanumericToBoolean(_flip);
            }

            if (httpd_query_key_value(_query, "dcw", _valuechar, 30) == ESP_OK)
            {
                std::string _dcw = std::string(_valuechar);
                CFstatus.ImageDcw = alphanumericToBoolean(_dcw);
            }

            if (httpd_query_key_value(_query, "den", _valuechar, 30) == ESP_OK)
            {
                std::string _idlv = std::string(_valuechar);
                if (isStringNumeric(_idlv))
                {
                    int _ImageDenoiseLevel = std::stoi(_valuechar);
                    if (CCstatus.CamSensor_id == OV2640_PID)
                    {
                        CFstatus.ImageDenoiseLevel = 0;
                    }
                    else
                    {
                        CFstatus.ImageDenoiseLevel = clipInt(_ImageDenoiseLevel, 8, 0);
                    }
                }
            }

            if (httpd_query_key_value(_query, "zoom", _valuechar, 30) == ESP_OK)
            {
                std::string _zoom = std::string(_valuechar);
                CFstatus.ImageZoomEnabled = alphanumericToBoolean(_zoom);
            }

            if (httpd_query_key_value(_query, "zoomx", _valuechar, 30) == ESP_OK)
            {
                std::string _zoomx = std::string(_valuechar);
                if (isStringNumeric(_zoomx))
                {
                    int _ImageZoomOffsetX = std::stoi(_valuechar);
                    if (CCstatus.CamSensor_id == OV2640_PID)
                    {
                        CFstatus.ImageZoomOffsetX = clipInt(_ImageZoomOffsetX, 480, -480);
                    }
                    else if (CCstatus.CamSensor_id == OV3660_PID)
                    {
                        CFstatus.ImageZoomOffsetX = clipInt(_ImageZoomOffsetX, 704, -704);
                    }
                    else if (CCstatus.CamSensor_id == OV5640_PID)
                    {
                        CFstatus.ImageZoomOffsetX = clipInt(_ImageZoomOffsetX, 960, -960);
                    }
                }
            }

            if (httpd_query_key_value(_query, "zoomy", _valuechar, 30) == ESP_OK)
            {
                std::string _zoomy = std::string(_valuechar);
                if (isStringNumeric(_zoomy))
                {
                    int _ImageZoomOffsetY = std::stoi(_valuechar);
                    if (CCstatus.CamSensor_id == OV2640_PID)
                    {
                        CFstatus.ImageZoomOffsetY = clipInt(_ImageZoomOffsetY, 360, -360);
                    }
                    else if (CCstatus.CamSensor_id == OV3660_PID)
                    {
                        CFstatus.ImageZoomOffsetY = clipInt(_ImageZoomOffsetY, 528, -528);
                    }
                    else if (CCstatus.CamSensor_id == OV5640_PID)
                    {
                        CFstatus.ImageZoomOffsetY = clipInt(_ImageZoomOffsetY, 720, -720);
                    }
                }
            }

            if (httpd_query_key_value(_query, "zooms", _valuechar, 30) == ESP_OK)
            {
                std::string _zooms = std::string(_valuechar);
                if (isStringNumeric(_zooms))
                {
                    int _ImageZoomSize = std::stoi(_valuechar);
                    if (CCstatus.CamSensor_id == OV2640_PID)
                    {
                        CFstatus.ImageZoomSize = clipInt(_ImageZoomSize, 29, 0);
                    }
                    else if (CCstatus.CamSensor_id == OV3660_PID)
                    {
                        CFstatus.ImageZoomSize = clipInt(_ImageZoomSize, 43, 0);
                    }
                    else if (CCstatus.CamSensor_id == OV5640_PID)
                    {
                        CFstatus.ImageZoomSize = clipInt(_ImageZoomSize, 59, 0);
                    }
                }
            }

            if (httpd_query_key_value(_query, "ledi", _valuechar, 30) == ESP_OK)
            {
                std::string _ledi = std::string(_valuechar);
                if (isStringNumeric(_ledi))
                {
                    int _ImageLedIntensity = std::stoi(_valuechar);
                    CFstatus.ImageLedIntensity = Camera.SetLEDIntensity(_ImageLedIntensity);
                }
            }

            if (_task.compare("cam_settings") == 0)
            {
                // wird aufgerufen, wenn das Referenzbild + Kameraeinstellungen gespeichert wurden
                setCFstatusToCCstatus(); // CFstatus >>> CCstatus

                // Kameraeinstellungen wurden verädert
                CFstatus.changedCameraSettings = true;

                ESP_LOGD(TAG, "Cam Settings set");
                std::string _zw = "CamSettingsSet";
                httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
                httpd_resp_send(req, _zw.c_str(), _zw.length());
            }
            else
            {
                // wird aufgerufen, wenn ein neues Referenzbild erstellt oder aktualisiert wurde
                // CFstatus >>> Kamera
                setCFstatusToCam();

                Camera.SetQualityZoomSize(CFstatus.ImageQuality, CFstatus.ImageFrameSize, CFstatus.ImageZoomEnabled, CFstatus.ImageZoomOffsetX, CFstatus.ImageZoomOffsetY, CFstatus.ImageZoomSize, CFstatus.ImageVflip);
                // Camera.SetZoomSize(CFstatus.ImageZoomEnabled, CFstatus.ImageZoomOffsetX, CFstatus.ImageZoomOffsetY, CFstatus.ImageZoomSize, CFstatus.ImageVflip);

                // Kameraeinstellungen wurden verädert
                CFstatus.changedCameraSettings = true;

                ESP_LOGD(TAG, "test_take - vor TakeImage");
                std::string image_temp = flowctrl.doSingleStep("[TakeImage]", _host);
                httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
                httpd_resp_send(req, image_temp.c_str(), image_temp.length());
            }
        }

        if (_task.compare("test_align") == 0)
        {
            std::string _host = "";

            if (httpd_query_key_value(_query, "host", _valuechar, 30) == ESP_OK)
            {
                _host = std::string(_valuechar);
            }

            std::string zw = flowctrl.doSingleStep("[Alignment]", _host);
            httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
            httpd_resp_send(req, zw.c_str(), zw.length());
        }
    }
    else
    {
        std::string _zw = "DeviceIsBusy";
        httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
        httpd_resp_send(req, _zw.c_str(), _zw.length());
    }

#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_editflow - Done");
#endif

    return ESP_OK;
}

esp_err_t handler_statusflow(httpd_req_t *req)
{
#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_statusflow - Start");
#endif

    const char *resp_str;
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");

    if (bTaskAutoFlowCreated)
    {
#ifdef DEBUG_DETAIL_ON
        ESP_LOGD(TAG, "handler_statusflow: %s", req->uri);
#endif

        string *zw = flowctrl.getActStatusWithTime();
        resp_str = zw->c_str();

        httpd_resp_send(req, resp_str, HTTPD_RESP_USE_STRLEN);
    }
    else
    {
        resp_str = "Flow task not yet created";
        httpd_resp_send(req, resp_str, HTTPD_RESP_USE_STRLEN);
    }

#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_statusflow - Done");
#endif

    return ESP_OK;
}

esp_err_t handler_cputemp(httpd_req_t *req)
{
#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_cputemp - Start");
#endif

    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    httpd_resp_send(req, std::to_string((int)temperatureRead()).c_str(), HTTPD_RESP_USE_STRLEN);

#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_cputemp - End");
#endif

    return ESP_OK;
}

esp_err_t handler_rssi(httpd_req_t *req)
{
#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_rssi - Start");
#endif

    if (getWIFIisConnected())
    {
        httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
        httpd_resp_send(req, std::to_string(get_WIFI_RSSI()).c_str(), HTTPD_RESP_USE_STRLEN);
    }
    else
    {
        httpd_resp_send_err(req, HTTPD_403_FORBIDDEN, "WIFI not (yet) connected: REST API /rssi not available!");
        return ESP_ERR_NOT_FOUND;
    }

#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_rssi - End");
#endif

    return ESP_OK;
}

esp_err_t handler_current_date(httpd_req_t *req)
{
#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_uptime - Start");
#endif

    std::string formatedDateAndTime = getCurrentTimeString("%Y-%m-%d %H:%M:%S");
    // std::string formatedDate = getCurrentTimeString("%Y-%m-%d");

    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    httpd_resp_send(req, formatedDateAndTime.c_str(), formatedDateAndTime.length());

    /* Respond with an empty chunk to signal HTTP response completion */
    httpd_resp_sendstr_chunk(req, NULL);

#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_uptime - End");
#endif

    return ESP_OK;
}

esp_err_t handler_uptime(httpd_req_t *req)
{
#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_uptime - Start");
#endif

    std::string formatedUptime = getFormatedUptime(false);

    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    httpd_resp_send(req, formatedUptime.c_str(), formatedUptime.length());

#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_uptime - End");
#endif

    return ESP_OK;
}

esp_err_t handler_prevalue(httpd_req_t *req)
{
#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_prevalue - Start");
    ESP_LOGD(TAG, "handler_prevalue: %s", req->uri);
#endif

    // Default usage message when handler gets called without any parameter
    const std::string RESTUsageInfo =
        "00: Handler usage:<br>"
        "- To retrieve actual PreValue, please provide only a numbersname, e.g. /setPreValue?numbers=main<br>"
        "- To set PreValue to a new value, please provide a numbersname and a value, e.g. /setPreValue?numbers=main&value=1234.5678<br>"
        "NOTE:<br>"
        "value >= 0.0: Set PreValue to provided value<br>"
        "value <  0.0: Set PreValue to actual RAW value (as long RAW value is a valid number, without N)";

    // Default return error message when no return is programmed
    std::string sReturnMessage = "E90: Uninitialized";

    char _query[100];
    char _numbersname[50] = "default";
    char _value[20] = "";

    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");

    if (httpd_req_get_url_query_str(req, _query, 100) == ESP_OK)
    {
#ifdef DEBUG_DETAIL_ON
        ESP_LOGD(TAG, "Query: %s", _query);
#endif

        if (httpd_query_key_value(_query, "numbers", _numbersname, 50) != ESP_OK)
        {
            // If request is incomplete
            sReturnMessage = "E91: Query parameter incomplete or not valid!<br> "
                             "Call /setPreValue to show REST API usage info and/or check documentation";
            httpd_resp_send(req, sReturnMessage.c_str(), sReturnMessage.length());
            return ESP_FAIL;
        }

        if (httpd_query_key_value(_query, "value", _value, 20) == ESP_OK)
        {
#ifdef DEBUG_DETAIL_ON
            ESP_LOGD(TAG, "Value: %s", _value);
#endif
        }
    }
    else
    {
        // if no parameter is provided, print handler usage
        httpd_resp_send(req, RESTUsageInfo.c_str(), RESTUsageInfo.length());
        return ESP_OK;
    }

    if (strlen(_value) == 0)
    {
        // If no value is povided --> return actual PreValue
        sReturnMessage = flowctrl.GetPrevalue(std::string(_numbersname));

        if (sReturnMessage.empty())
        {
            sReturnMessage = "E92: Numbers name not found";
            httpd_resp_send(req, sReturnMessage.c_str(), sReturnMessage.length());
            return ESP_FAIL;
        }
    }
    else
    {
        // New value is positive: Set PreValue to provided value and return value
        // New value is negative and actual RAW value is a valid number: Set PreValue to RAW value and return value
        LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "REST API handler_prevalue called: numbersname: " + std::string(_numbersname) + ", value: " + std::string(_value));

        if (!flowctrl.UpdatePrevalue(_value, _numbersname, true))
        {
            sReturnMessage = "E93: Update request rejected. Please check device logs for more details";
            httpd_resp_send(req, sReturnMessage.c_str(), sReturnMessage.length());
            return ESP_FAIL;
        }

        sReturnMessage = flowctrl.GetPrevalue(std::string(_numbersname));

        if (sReturnMessage.empty())
        {
            sReturnMessage = "E94: Numbers name not found";
            httpd_resp_send(req, sReturnMessage.c_str(), sReturnMessage.length());
            return ESP_FAIL;
        }
    }

    httpd_resp_send(req, sReturnMessage.c_str(), sReturnMessage.length());

#ifdef DEBUG_DETAIL_ON
    LogFile.WriteHeapInfo("handler_prevalue - End");
#endif

    return ESP_OK;
}

void task_autodoFlow(void *pvParameter)
{
    int64_t fr_start;
    int64_t scheduledStartUs = 0;

    bTaskAutoFlowCreated = true;

    if (!isPlannedReboot && (esp_reset_reason() == ESP_RST_PANIC))
    {
        flowctrl.setActStatus("Initialization (delayed)");
        // #ifdef ENABLE_MQTT
        // MQTTPublish(mqttServer_getMainTopic() + "/" + "status", "Initialization (delayed)", false); // Right now, not possible -> MQTT Service is going to be started later
        // #endif //ENABLE_MQTT
        vTaskDelay(60 * 5000 / portTICK_PERIOD_MS); // Wait 5 minutes to give time to do an OTA update or fetch the log
    }

    ESP_LOGD(TAG, "task_autodoFlow: start");
    doInit();
    servicePendingImage();

    flowctrl.setAutoStartInterval(auto_interval);
    autostartIsEnabled = flowctrl.getIsAutoStart();

    if (isSetupModusActive())
    {
        LogFile.WriteToFile(ESP_LOG_INFO, TAG, "We are in Setup Mode -> Not starting Auto Flow!");
        autostartIsEnabled = false;
        // 15.7.0 Setup Wizard cannot take a Reference Picture #2953
        // std::string zw_time = getCurrentTimeString(LOGFILE_TIME_FORMAT);
        // flowctrl.doFlowTakeImageOnly(zw_time);
    }

    if (autostartIsEnabled)
    {
        LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Starting Flow...");
    }
    else
    {
        LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Autostart is not enabled -> Not starting Flow");
    }

    while (autostartIsEnabled)
    {
        LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "----------------------------------------------------------------"); // Clear separation between runs
        time_t roundStartTime = getUpTime();

        std::string _zw = "Round #" + std::to_string(++countRounds) + " started";
        LogFile.WriteToFile(ESP_LOG_INFO, TAG, _zw);

        fr_start = esp_timer_get_time();
        // An explicit early manual wake starts a new cadence from that run.
        if (!scheduledStartUs || fr_start < scheduledStartUs) scheduledStartUs = fr_start;

        bool roundAttempted = false;
        bool roundSucceeded = false;
        if (flowisrunning)
        {
#ifdef DEBUG_DETAIL_ON
            ESP_LOGD(TAG, "Autoflow: doFlow is already running!");
#endif
        }
        else
        {
#ifdef DEBUG_DETAIL_ON
            ESP_LOGD(TAG, "Autoflow: doFlow is started");
#endif
            flowisrunning = true;
            roundAttempted = true;
            roundSucceeded = doflow();
            servicePendingImage();
#ifdef DEBUG_DETAIL_ON
            ESP_LOGD(TAG, "Remove older log files");
#endif
            LogFile.RemoveOldLogFile();
            LogFile.RemoveOldDataLog();
        }

        // Round finished -> Logfile
        const char* roundOutcome = !roundAttempted ? " skipped: processing already active (" :
                                   roundSucceeded ? " completed (" : " failed (";
        LogFile.WriteToFile(roundSucceeded ? ESP_LOG_INFO : ESP_LOG_WARN, TAG,
            "Round #" + std::to_string(countRounds) + roundOutcome +
            std::to_string(getUpTime() - roundStartTime) + " seconds)");

        // CPU Temp -> Logfile
        LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "CPU Temperature: " + std::to_string((int)temperatureRead()) + "°C");

        // WIFI Signal Strength (RSSI) -> Logfile
        LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "WIFI Signal (RSSI): " + std::to_string(get_WIFI_RSSI()) + "dBm");

        // Check if time is synchronized (if NTP is configured)
        if (getUseNtp() && !getTimeIsSet())
        {
            LogFile.WriteToFile(ESP_LOG_WARN, TAG, "Time server is configured, but time is not yet set!");
            StatusLED(TIME_CHECK, 1, false);
        }

#if (defined WLAN_USE_MESH_ROAMING && defined WLAN_USE_MESH_ROAMING_ACTIVATE_CLIENT_TRIGGERED_QUERIES)
        wifiRoamingQuery();
#endif

// Scan channels and check if an AP with better RSSI is available, then disconnect and try to reconnect to AP with better RSSI
// NOTE: Keep this direct before the following task delay, because scan is done in blocking mode and this takes ca. 1,5 - 2s.
#ifdef WLAN_USE_ROAMING_BY_SCANNING
        wifiRoamByScanning();
#endif

        const int64_t nowUs = esp_timer_get_time();
        const auto next = CycleSchedule::after(scheduledStartUs, nowUs,
                                               static_cast<int64_t>(auto_interval)*1000);
        if (!next.valid) {
            LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Invalid capture schedule; automatic runs stopped");
            autostartIsEnabled = false;
            break;
        }
        scheduledStartUs = next.atUs;
        CycleTelemetry::schedule(next.missed);
        if (next.missed)
            LogFile.WriteToFile(ESP_LOG_WARN, TAG, "Capture schedule missed slots: " + std::to_string(next.missed));
        const int64_t tickUs = static_cast<int64_t>(portTICK_PERIOD_MS)*1000;
        const int64_t waitUs = next.atUs-nowUs;
        if (waitUs > 0) vTaskDelay(static_cast<TickType_t>(waitUs/tickUs+(waitUs%tickUs != 0)));
    }

    while (1)
    {
        // Keep flow task running to handle necessary sub tasks like reboot handler, etc..
        vTaskDelay(2000 / portTICK_PERIOD_MS);
    }

    vTaskDelete(NULL); // Delete this task if it exits from the loop above
    xHandletask_autodoFlow = NULL;

    ESP_LOGD(TAG, "task_autodoFlow: end");
}

void InitializeFlowTask(void)
{
    BaseType_t xReturned;

    ESP_LOGD(TAG, "getESPHeapInfo: %s", getESPHeapInfo().c_str());

    uint32_t stackSize = 16 * 1024;
    xReturned = xTaskCreatePinnedToCore(&task_autodoFlow, "task_autodoFlow", stackSize, NULL, tskIDLE_PRIORITY + 2, &xHandletask_autodoFlow, 0);

    if (xReturned != pdPASS)
    {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Creation task_autodoFlow failed. Requested stack size:" + std::to_string(stackSize));
        LogFile.WriteHeapInfo("Creation task_autodoFlow failed");
    }

    ESP_LOGD(TAG, "getESPHeapInfo: %s", getESPHeapInfo().c_str());
}

void register_server_main_flow_task_uri(httpd_handle_t server)
{
    ESP_LOGI(TAG, "server_main_flow_task - Registering URI handlers");

    httpd_uri_t camuri = {};
    camuri.method = HTTP_GET;

    camuri.uri = "/doinit";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_init);
    camuri.user_ctx = (void *)"Light On";
    httpd_register_uri_handler(server, &camuri);

    // Legacy API => New: "/setPreValue"
    camuri.uri = "/setPreValue.html";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_prevalue);
    camuri.user_ctx = (void *)"Prevalue";
    httpd_register_uri_handler(server, &camuri);

    camuri.uri = "/setPreValue";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_prevalue);
    camuri.user_ctx = (void *)"Prevalue";
    httpd_register_uri_handler(server, &camuri);

    camuri.uri = "/flow_start";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_flow_start);
    camuri.user_ctx = (void *)"Flow Start";
    httpd_register_uri_handler(server, &camuri);

    camuri.uri = "/statusflow.html";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_statusflow);
    camuri.user_ctx = (void *)"Light Off";
    httpd_register_uri_handler(server, &camuri);

    camuri.uri = "/statusflow";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_statusflow);
    camuri.user_ctx = (void *)"Light Off";
    httpd_register_uri_handler(server, &camuri);

    // Legacy API => New: "/cpu_temperature"
    camuri.uri = "/cputemp.html";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_cputemp);
    camuri.user_ctx = (void *)"Light Off";
    httpd_register_uri_handler(server, &camuri);

    camuri.uri = "/cpu_temperature";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_cputemp);
    camuri.user_ctx = (void *)"Light Off";
    httpd_register_uri_handler(server, &camuri);

    // Legacy API => New: "/rssi"
    camuri.uri = "/rssi.html";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_rssi);
    camuri.user_ctx = (void *)"Light Off";
    httpd_register_uri_handler(server, &camuri);

    camuri.uri = "/rssi";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_rssi);
    camuri.user_ctx = (void *)"Light Off";
    httpd_register_uri_handler(server, &camuri);

    camuri.uri = "/date";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_current_date);
    camuri.user_ctx = (void *)"Light Off";
    httpd_register_uri_handler(server, &camuri);

    camuri.uri = "/uptime";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_uptime);
    camuri.user_ctx = (void *)"Light Off";
    httpd_register_uri_handler(server, &camuri);

    camuri.uri = "/editflow";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_editflow);
    camuri.user_ctx = (void *)"EditFlow";
    httpd_register_uri_handler(server, &camuri);

    // Legacy API => New: "/value"
    camuri.uri = "/value.html";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_wasserzaehler);
    camuri.user_ctx = (void *)"Value";
    httpd_register_uri_handler(server, &camuri);

    camuri.uri = "/value";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_wasserzaehler);
    camuri.user_ctx = (void *)"Value";
    httpd_register_uri_handler(server, &camuri);

    // Legacy API => New: "/value"
    camuri.uri = "/wasserzaehler.html";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_wasserzaehler);
    camuri.user_ctx = (void *)"Wasserzaehler";
    httpd_register_uri_handler(server, &camuri);

    camuri.uri = "/json";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_json);
    camuri.user_ctx = (void *)"JSON";
    httpd_register_uri_handler(server, &camuri);

    camuri.uri = "/cycle_timing";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_cycle_timing);
    camuri.user_ctx = NULL;
    httpd_register_uri_handler(server, &camuri);

    camuri.uri = "/ota_health";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_ota_health);
    camuri.user_ctx = NULL;
    httpd_register_uri_handler(server, &camuri);

    camuri.uri = "/image_archive_settings";
    camuri.method = HTTP_GET;
    camuri.handler = APPLY_BASIC_AUTH_FILTER(ImageArchive::archiveSettingsHttp);
    camuri.user_ctx = NULL;
    if(httpd_register_uri_handler(server,&camuri)!=ESP_OK)LogFile.WriteToFile(ESP_LOG_ERROR,TAG,"Could not register archive settings read");
    camuri.method = HTTP_POST;
    if(httpd_register_uri_handler(server,&camuri)!=ESP_OK)LogFile.WriteToFile(ESP_LOG_ERROR,TAG,"Could not register archive settings save");
    camuri.method = HTTP_GET;

    camuri.uri = "/meter_profile";
    camuri.method = HTTP_GET;
    camuri.handler = APPLY_BASIC_AUTH_FILTER(meter::profileSettingsHttp);
    camuri.user_ctx = NULL;
    if(httpd_register_uri_handler(server,&camuri)!=ESP_OK)LogFile.WriteToFile(ESP_LOG_ERROR,TAG,"Could not register meter profile read");
    camuri.method = HTTP_POST;
    if(httpd_register_uri_handler(server,&camuri)!=ESP_OK)LogFile.WriteToFile(ESP_LOG_ERROR,TAG,"Could not register meter profile save");
    camuri.method = HTTP_GET;

    camuri.uri = "/image_archive_status";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_image_archive_status);
    camuri.user_ctx = NULL;
    httpd_register_uri_handler(server, &camuri);

    camuri.uri = "/meter_accounting";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_meter_accounting);
    camuri.user_ctx = NULL;
    httpd_register_uri_handler(server, &camuri);

    camuri.uri = "/meter_history";camuri.method=HTTP_POST;
    camuri.handler=APPLY_BASIC_AUTH_FILTER(handler_meter_history_refresh);
    if(httpd_register_uri_handler(server,&camuri)!=ESP_OK)LogFile.WriteToFile(ESP_LOG_ERROR,TAG,"Could not register history refresh");
    camuri.method=HTTP_GET;camuri.handler=APPLY_BASIC_AUTH_FILTER(handler_meter_history_status);
    if(httpd_register_uri_handler(server,&camuri)!=ESP_OK)LogFile.WriteToFile(ESP_LOG_ERROR,TAG,"Could not register history status");

    camuri.uri = "/polar_runtime_test";
    camuri.method = HTTP_POST;
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_polar_test_start);
    camuri.user_ctx = NULL;
    httpd_register_uri_handler(server, &camuri);
    camuri.method = HTTP_GET;
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_polar_test_status);
    httpd_register_uri_handler(server, &camuri);

    camuri.uri = "/polar_frame_test";camuri.method=HTTP_POST;
    camuri.handler=APPLY_BASIC_AUTH_FILTER(handler_polar_frame_test_start);
    httpd_register_uri_handler(server,&camuri);
    camuri.method=HTTP_GET;camuri.handler=APPLY_BASIC_AUTH_FILTER(handler_polar_frame_test_status);
    httpd_register_uri_handler(server,&camuri);

    camuri.uri = "/polar_jpeg_test";camuri.method=HTTP_POST;
    camuri.handler=APPLY_BASIC_AUTH_FILTER(handler_polar_frame_test_start);
    httpd_register_uri_handler(server,&camuri);
    camuri.method=HTTP_GET;camuri.handler=APPLY_BASIC_AUTH_FILTER(handler_polar_frame_test_status);
    httpd_register_uri_handler(server,&camuri);

    camuri.uri = "/heap";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_get_heap);
    camuri.user_ctx = (void *)"Heap";
    httpd_register_uri_handler(server, &camuri);

    camuri.uri = "/stream";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_stream);
    camuri.user_ctx = (void *)"stream";
    httpd_register_uri_handler(server, &camuri);

    /** will handle metrics requests */
    camuri.uri = "/metrics";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_openmetrics);
    camuri.user_ctx = (void *)"metrics";
    httpd_register_uri_handler(server, &camuri);

    /** when adding a new handler, make sure to increment the value for config.max_uri_handlers in `main/server_main.cpp` */
}
