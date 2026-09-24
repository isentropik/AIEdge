#include "server_ota.h"
#include "UpdateAccess.h"
#include "RuntimeBundle.h"
#include "ManagedBundleTransaction.h"
#include "StageDeviceBundle.h"
#include "../jomjol_flowcontroll/ImageArchiveSha.h"
#include "ProcessingAccess.h"
#include "CameraAccess.h"
#include "PolarIdentity.h"

#include <string>
#include <atomic>
#include "string.h"

/* TODO Rethink the usage of the int watchdog. It is no longer to be used, see
https://docs.espressif.com/projects/esp-idf/en/latest/esp32/migration-guides/release-5.x/5.0/system.html?highlight=esp_int_wdt */
#include "esp_private/esp_int_wdt.h"

#include <esp_task_wdt.h>


#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_system.h"
#include "esp_log.h"
#include <esp_ota_ops.h>
#include "esp_http_client.h"
#include "esp_flash_partitions.h"
#include "esp_partition.h"
#include <nvs.h>
#include "esp_app_format.h"
#include "nvs_flash.h"
#include "driver/gpio.h"
// #include "protocol_examples_common.h"
#include "errno.h"

#include <sys/stat.h>

#include "MainFlowControl.h"
#include "server_file.h"
#include "server_GPIO.h"
#ifdef ENABLE_MQTT
    #include "interface_mqtt.h"
#endif //ENABLE_MQTT
#include "ClassControllCamera.h"
#include "connect_wlan.h"


#include "ClassLogFile.h"

#include "Helper.h"
#include "statusled.h"
#include "basic_auth.h"
#include "../../include/defines.h"

/*an ota data write buffer ready to write to the flash*/
static char ota_write_data[SERVER_OTA_SCRATCH_BUFSIZE + 1] = { 0 };

static const char *TAG = "OTA";

esp_err_t handler_reboot(httpd_req_t *req);
static bool ota_update_task(std::string fn, bool (*prepareBoot)(const esp_partition_t*, void*) = nullptr, void* context = nullptr);

std::string _file_name_update;
bool initial_setup = false;
static std::atomic<bool> startupUpdateFinished{true};


static void infinite_loop(void)
{
    int i = 0;
    LogFile.WriteToFile(ESP_LOG_INFO, TAG, "When a new firmware is available on the server, press the reset button to download it");
    while(1) {
        LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Waiting for a new firmware... (" + to_string(++i) + ")");
        vTaskDelay(1000 / portTICK_PERIOD_MS);
    }
}


static bool performStartupUpdate()
{
    StatusLED(AP_OR_OTA, 1, true);  // Signaling an OTA update
    
    std::string filetype = toUpper(getFileType(_file_name_update));

  	LogFile.WriteToFile(ESP_LOG_INFO, TAG, "File: " + _file_name_update + " Filetype: " + filetype);

    if (filetype == "ZIP")
    {
        std::string in, outHtml, outHtmlTmp, outHtmlOld, outbin, zw, retfirmware;

        outHtml = "/sdcard/html";
        outHtmlTmp = "/sdcard/html_tmp";
        outHtmlOld = "/sdcard/html_old";
        outbin = "/sdcard/firmware";

        /* Remove the old and tmp html folder in case they still exist */
        removeFolder(outHtmlTmp.c_str(), TAG);
        removeFolder(outHtmlOld.c_str(), TAG);

        /* Extract the ZIP file. The content of the html folder gets extracted to the temporar folder html-temp. */
        LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Extracting ZIP file " + _file_name_update + "...");
        retfirmware = unzip_new(_file_name_update, outHtmlTmp+"/", outHtml+"/", outbin+"/", "/sdcard/", initial_setup);
        if (retfirmware.empty() || retfirmware == "ERROR") {
            LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "OTA extraction failed or firmware image missing");
            return false;
        }
    	LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Files unzipped.");

        /* ZIP file got extracted, replace the old html folder with the new one */
        LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Renaming folder " + outHtml + " to " + outHtmlOld + "...");
        RenameFolder(outHtml, outHtmlOld);
        LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Renaming folder " + outHtmlTmp + " to " + outHtml + "...");
        RenameFolder(outHtmlTmp, outHtml);
        LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Deleting folder " + outHtmlOld + "...");
        removeFolder(outHtmlOld.c_str(), TAG);

        if (retfirmware.length() > 0)
        {
            LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Found firmware.bin");
            if (!ota_update_task(retfirmware)) return false;
        }

        LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Trigger reboot due to firmware update");
        doRebootOTA();
    } else if (filetype == "BIN")
    {
       	LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Do firmware update - file: " + _file_name_update);
        if (!ota_update_task(_file_name_update)) return false;
        LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Trigger reboot due to firmware update");
        doRebootOTA();
    }
    else
    {
    	LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Only ZIP-Files support for update during startup!");
    }
    return false; // Successful reboot does not return.
}

void task_do_Update_ZIP(void *pvParameter)
{
    performStartupUpdate(); // Local buffers are destroyed before deleting task.
    LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Startup update failed; continuing existing firmware");
    startupUpdateFinished.store(true, std::memory_order_release);
    vTaskDelete(nullptr);
}


void CheckUpdate()
{
#ifdef METER_REQUIRE_BUNDLE
    // Old update markers cannot bypass the managed app/assets identity contract.
    // Preserve any marker for inspection instead of deleting or applying it.
    LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "Legacy startup updates disabled; use verified bundles");
    return;
#endif

 	FILE *pfile;
    if ((pfile = fopen("/sdcard/update.txt", "r")) == NULL)
    {
		LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "No pending update");
        return;
	}

	char zw[1024] = "";
	fgets(zw, 1024, pfile);
    _file_name_update = std::string(zw);
    if (fgets(zw, 1024, pfile))
	{
		std::string _szw = std::string(zw);
        if (_szw == "init")
        {
       		LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Inital Setup triggered");
        }
	}

    fclose(pfile);
    DeleteFile("/sdcard/update.txt");   // Prevent Boot Loop!!!
	LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Start update process (" + _file_name_update + ")");


    startupUpdateFinished.store(false, std::memory_order_release);
    if (xTaskCreate(&task_do_Update_ZIP, "task_do_Update_ZIP", configMINIMAL_STACK_SIZE * 35, NULL, tskIDLE_PRIORITY+1, NULL) != pdPASS) {
        startupUpdateFinished.store(true, std::memory_order_release);
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Could not start OTA task; continuing existing firmware");
        return;
    }
    while(!startupUpdateFinished.load(std::memory_order_acquire)) {
        vTaskDelay(1000 / portTICK_PERIOD_MS);
    }
}


static bool ota_update_task(std::string fn, bool (*prepareBoot)(const esp_partition_t*, void*), void* context)
{
    UpdateAccess update;if(!update)return false;
    const esp_partition_t* configured = esp_ota_get_boot_partition();
    const esp_partition_t* running = esp_ota_get_running_partition();
    const esp_partition_t* target = esp_ota_get_next_update_partition(nullptr);
    if (!configured || !running || !target || configured->address != running->address ||
        target->address == running->address) {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "OTA partition state is missing or conflicting");
        return false;
    }
    FILE* file = fopen(fn.c_str(), "rb");
    if (!file) return false;
    esp_ota_handle_t handle = 0;
    bool active = false;
    auto fail = [&]() {
        if (active) { esp_ota_abort(handle); active = false; }
        if (file) { fclose(file); file = nullptr; }
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "OTA failed; inspect boot state before retrying");
        return false;
    };
    if (fseek(file, 0, SEEK_END) != 0) return fail();
    const long length = ftell(file);
    constexpr size_t headerBytes = sizeof(esp_image_header_t) +
        sizeof(esp_image_segment_header_t) + sizeof(esp_app_desc_t);
    if (length <= 0 || static_cast<size_t>(length) < headerBytes ||
        static_cast<size_t>(length) > target->size || fseek(file, 0, SEEK_SET) != 0)
        return fail();
    size_t count = fread(ota_write_data, 1, SERVER_OTA_SCRATCH_BUFSIZE, file);
    if (count < headerBytes || ferror(file)) return fail();
    esp_app_desc_t candidate{};
    memcpy(&candidate, ota_write_data + sizeof(esp_image_header_t) + sizeof(esp_image_segment_header_t), sizeof(candidate));
    const esp_partition_t* invalid = esp_ota_get_last_invalid_partition();
    esp_app_desc_t invalidInfo{};
    if (invalid && esp_ota_get_partition_description(invalid, &invalidInfo) == ESP_OK &&
        memcmp(invalidInfo.version, candidate.version, sizeof(candidate.version)) == 0) {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "OTA version matches previously invalid firmware");
        return fail();
    }
    if (esp_ota_begin(target, static_cast<size_t>(length), &handle) != ESP_OK) return fail();
    active = true;
    size_t written = 0;
    while (count) {
        if (count > static_cast<size_t>(length) - written ||
            esp_ota_write(handle, ota_write_data, count) != ESP_OK) return fail();
        written += count;
        vTaskDelay(1);
        count = fread(ota_write_data, 1, SERVER_OTA_SCRATCH_BUFSIZE, file);
        if (ferror(file)) return fail();
    }
    if (written != static_cast<size_t>(length)) return fail();
    const int closed = fclose(file); file = nullptr;
    if (closed != 0) return fail();
    const esp_err_t validated = esp_ota_end(handle);
    active = false; // esp_ota_end consumes the handle even on validation failure.
    if (validated != ESP_OK) return fail();
    // Managed bundles must verify flashed identity and publish their asset index
    // after SDK validation, before any boot-partition change. Failure leaves the
    // running image selected; the inactive flash contents may have changed.
    if (prepareBoot && !prepareBoot(target, context)) return fail();
    if (esp_ota_set_boot_partition(target) != ESP_OK) return fail();
    const auto* selected=esp_ota_get_boot_partition();
    if(!selected || selected->address!=target->address || selected->size!=target->size)
        return fail(); // Boot metadata may have changed; do not automatically retry.
    return true;
}


// This coordinator is not registered as an HTTP handler. The managed update
// route must first establish exclusive immutable-tree ownership and approval.
static std::string bundlePartitionHash(const esp_partition_t* partition) {
    uint8_t digest[32];
    if (!partition || esp_partition_get_sha256(partition,digest)!=ESP_OK) return "";
    const char* hex="0123456789abcdef";std::string value;
    for (uint8_t b:digest) {value+=hex[b>>4];value+=hex[b&15];}
    return value;
}
struct BundleFlashAdapter {
    bool writeAndSelect(const std::string& path,
                        std::function<bool(const std::string&)> prepare) {
        auto callback=[](const esp_partition_t* target,void* context) {
            const auto* action=static_cast<const std::function<bool(const std::string&)>*>(context);
            const auto hash=bundlePartitionHash(target);
            return !hash.empty() && (*action)(hash);
        };
        return ota_update_task(path,callback,&prepare);
    }
};
// Not an HTTP endpoint: caller must use a worker and an approved managed route.
MeterBundle::StageResult stageManagedBundle(const std::string& zip,const std::string& id) {
    UpdateAccess update;if(!update)return MeterBundle::StageResult::Conflict;
    // Exclusive UpdateAccess owns this fixed buffer. Do not open the log file
    // or allocate diagnostic strings while staging is using scarce SD/heap resources.
    static char firstFailure[512];
    firstFailure[0]='\0';
    const auto trace=[](const char* step,const char* path,uint64_t detail){
        if(!firstFailure[0]&&(strstr(step,"failed")||strcmp(step,"verify.fail")==0))
            snprintf(firstFailure,sizeof(firstFailure),"Bundle staging %s path=%s detail=%llu",step,path,static_cast<unsigned long long>(detail));
    };
    const auto result=MeterBundle::stageZip<ImageArchive::Sha256>(zip,"/sdcard/bundles",id,polar::modelIdentity,trace);
    if(firstFailure[0])LogFile.WriteToFile(ESP_LOG_ERROR,TAG,firstFailure);
    if(result==MeterBundle::StageResult::IoError)
        LogFile.WriteToFile(ESP_LOG_ERROR,TAG,"Bundle staging storage error; retained pending files for inspection");
    return result;
}
bool installManagedBundle(const std::string& id) {
    ProcessingAccess processing;if(!processing)return false;
    CameraAccess camera;if(!camera)return false;
    const auto running=bundlePartitionHash(esp_ota_get_running_partition());
    BundleFlashAdapter flash;
    return MeterBundle::install<ImageArchive::Sha256>("/sdcard/bundles",id,running,polar::modelIdentity,flash);
}

static void print_sha256 (const uint8_t *image_hash, const char *label)
{
    char hash_print[HASH_LEN * 2 + 1];
    hash_print[HASH_LEN * 2] = 0;
    for (int i = 0; i < HASH_LEN; ++i) {
        sprintf(&hash_print[i * 2], "%02x", image_hash[i]);
    }
    ESP_LOGI(TAG, "%s: %s", label, hash_print);
}


// Called before PSRAM/camera/reader initialization. It cannot establish health.
void CheckOTAUpdate(void)
{
    const esp_partition_t* running=esp_ota_get_running_partition();
    if(!running){
        LogFile.WriteToFile(ESP_LOG_ERROR,TAG,"OTA running partition unavailable; boot health unverified");
        return;
    }
    uint8_t digest[HASH_LEN]={};
    if(esp_partition_get_sha256(running,digest)==ESP_OK)
        print_sha256(digest,"SHA-256 for current firmware: ");
    else LogFile.WriteToFile(ESP_LOG_ERROR,TAG,"OTA running image hash unavailable");
    esp_ota_img_states_t state;
    const esp_err_t result=esp_ota_get_state_partition(running,&state);
    if(result==ESP_ERR_NOT_SUPPORTED){
        LogFile.WriteToFile(ESP_LOG_WARN,TAG,"OTA bootloader rollback is not supported; no recovery guarantee");
        return;
    }
    if(result!=ESP_OK){
        LogFile.WriteToFile(ESP_LOG_WARN,TAG,"OTA image state unavailable; boot health unverified");
        return;
    }
    if(state==ESP_OTA_IMG_PENDING_VERIFY){
        LogFile.WriteToFile(ESP_LOG_WARN,TAG,"OTA image pending verification; not accepted before hardware and reader health checks");
    }
    // Never mark valid or trigger rollback from this early observation.
    // A supported bootloader retains its pending-image policy across restart.
}


esp_err_t handler_ota_update(httpd_req_t *req)
{
#ifdef METER_REQUIRE_BUNDLE
    httpd_resp_set_status(req, "409 Conflict");
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_sendstr(req,
        "{\"error\":\"managed_bundle_required\",\"page\":\"/managed_update.html\"}");
#endif

#ifdef DEBUG_DETAIL_ON     
    LogFile.WriteHeapInfo("handler_ota_update - Start");    
#endif

    LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "handler_ota_update");
    char _query[200];
    char _filename[100];
    char _valuechar[30];    
    std::string fn = "/sdcard/firmware/";
    bool _file_del = false;
    std::string _task = "";

    if (httpd_req_get_url_query_str(req, _query, 200) == ESP_OK)
    {
        ESP_LOGD(TAG, "Query: %s", _query);
        
        if (httpd_query_key_value(_query, "task", _valuechar, 30) == ESP_OK)
        {
            ESP_LOGD(TAG, "task is found: %s", _valuechar);
            _task = std::string(_valuechar);
        }

        if (httpd_query_key_value(_query, "file", _filename, 100) == ESP_OK)
        {
            fn.append(_filename);
            ESP_LOGD(TAG, "File: %s", fn.c_str());
        }
        if (httpd_query_key_value(_query, "delete", _filename, 100) == ESP_OK)
        {
            fn.append(_filename);
            _file_del = true;
            ESP_LOGD(TAG, "Delete Default File: %s", fn.c_str());
        }

    }

    if (_task.compare("emptyfirmwaredir") == 0)
    {
        ESP_LOGD(TAG, "Start empty directory /firmware");
        delete_all_in_directory("/sdcard/firmware");
        std::string zw = "firmware directory deleted - v2\n";
        ESP_LOGD(TAG, "%s", zw.c_str());
        printf("Ausgabe: %s\n", zw.c_str());
    
        httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
        httpd_resp_send(req, zw.c_str(), strlen(zw.c_str())); 
        /* Respond with an empty chunk to signal HTTP response completion */
        httpd_resp_send_chunk(req, NULL, 0);  

        ESP_LOGD(TAG, "Done empty directory /firmware");
        return ESP_OK;
    }

    if (_task.compare("update") == 0)
    {
        std::string filetype = toUpper(getFileType(fn));
        if (filetype.length() == 0)
        {
            std::string zw = "Update failed - no file specified (zip, bin, tfl, tlite)";
            httpd_resp_sendstr_chunk(req, zw.c_str());
            httpd_resp_sendstr_chunk(req, NULL);  
            return ESP_OK;        
        }

        if ((filetype == "TFLITE") || (filetype == "TFL"))
        {
            std::string out = "/sdcard/config/" + getFileFullFileName(fn);
            DeleteFile(out);
            CopyFile(fn, out);
            DeleteFile(fn);

            const char*  resp_str = "Neural Network File copied.";
            httpd_resp_sendstr_chunk(req, resp_str);
            httpd_resp_sendstr_chunk(req, NULL);  
            return ESP_OK;
        }


        if ((filetype == "ZIP") || (filetype == "BIN"))
        {
           	FILE *pfile;
            LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Update for reboot");
            pfile = fopen("/sdcard/update.txt", "w");
            fwrite(fn.c_str(), fn.length(), 1, pfile);
            fclose(pfile);

            std::string zw = "reboot\n";
            httpd_resp_sendstr_chunk(req, zw.c_str());
            httpd_resp_sendstr_chunk(req, NULL);  
            ESP_LOGD(TAG, "Send reboot");
            return ESP_OK;                

        }

/*
        if (filetype == "BIN")
        {
            const char* resp_str; 

            DeleteMainFlowTask();
            gpio_handler_deinit();
            if (ota_update_task(fn))
            {
                std::string zw = "reboot\n";
                httpd_resp_sendstr_chunk(req, zw.c_str());
                httpd_resp_sendstr_chunk(req, NULL);  
                ESP_LOGD(TAG, "Send reboot");
                return ESP_OK;                
            }

            resp_str = "Error during Firmware Update!!!\nPlease check output of console.";
            httpd_resp_send(req, resp_str, strlen(resp_str));  

            #ifdef DEBUG_DETAIL_ON 
                LogFile.WriteHeapInfo("handler_ota_update - Done");    
            #endif

            return ESP_OK;
        }
*/

        std::string zw = "Update failed - no valid file specified (zip, bin, tfl, tlite)!";
        httpd_resp_sendstr_chunk(req, zw.c_str());
        httpd_resp_sendstr_chunk(req, NULL);  
        return ESP_OK;        
    }


    if (_task.compare("unziphtml") == 0)
    {
        ESP_LOGD(TAG, "Task unziphtml");
        std::string in, out, zw;

        in = "/sdcard/firmware/html.zip";
        out = "/sdcard/html";

        delete_all_in_directory(out);

        unzip(in, out+"/");
        zw = "Web Interface Update Successfull!\nNo reboot necessary";
        httpd_resp_send(req, zw.c_str(), strlen(zw.c_str()));
        httpd_resp_sendstr_chunk(req, NULL);  
        return ESP_OK;        
    }

    if (_file_del)
    {
        ESP_LOGD(TAG, "Delete !! _file_del: %s", fn.c_str());
        struct stat file_stat;
        int _result = stat(fn.c_str(), &file_stat);
        ESP_LOGD(TAG, "Ergebnis %d\n", _result);
        if (_result == 0) {
            ESP_LOGD(TAG, "Deleting file: %s", fn.c_str());
            /* Delete file */
            unlink(fn.c_str());
        }
        else
        {
            LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "File does not exist: " + fn);
        }
        /* Respond with an empty chunk to signal HTTP response completion */
        std::string zw = "file deleted\n";
        ESP_LOGD(TAG, "%s", zw.c_str());
        httpd_resp_send(req, zw.c_str(), strlen(zw.c_str()));
        httpd_resp_send_chunk(req, NULL, 0);
        return ESP_OK;
    }

    string zw = "ota without parameter - should not be the case!";
    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    httpd_resp_send(req, zw.c_str(), strlen(zw.c_str())); 
    httpd_resp_send_chunk(req, NULL, 0);  

    LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "ota without parameter - should not be the case!");

/*  
    const char* resp_str;    

    DeleteMainFlowTask();
    gpio_handler_deinit();
    if (ota_update_task(fn))
    {
        resp_str = "Firmware Update Successfull! You can restart now.";
    }
    else
    {
        resp_str = "Error during Firmware Update!!! Please check console output.";
    }

    httpd_resp_send(req, resp_str, strlen(resp_str));  
*/

    #ifdef DEBUG_DETAIL_ON 
        LogFile.WriteHeapInfo("handler_ota_update - Done");    
    #endif

    return ESP_OK;
}


void hard_restart() 
{
  esp_task_wdt_config_t twdt_config = {
    .timeout_ms = 1,
    .idle_core_mask = (1 << portNUM_PROCESSORS) - 1,    // Bitmask of all cores
    .trigger_panic = true,
  };
  ESP_ERROR_CHECK(esp_task_wdt_init(&twdt_config));

  esp_task_wdt_add(NULL);
  while(true);
}


void task_reboot(void *DeleteMainFlow)
{
    // write a reboot, to identify a reboot by purpouse
    FILE* pfile = fopen("/sdcard/reboot.txt", "w");
    std::string _s_zw= "reboot";
    fwrite(_s_zw.c_str(), strlen(_s_zw.c_str()), 1, pfile);
    fclose(pfile);

    vTaskDelay(3000 / portTICK_PERIOD_MS);

    if ((bool)DeleteMainFlow) {
        DeleteMainFlowTask();  // Kill autoflow task if executed in extra task, if not don't kill parent task
    }

    Camera.LightOnOff(false);
    StatusLEDOff();

    /* Stop service tasks */
    #ifdef ENABLE_MQTT
        MQTTdestroy_client(true);
    #endif //ENABLE_MQTT
    gpio_handler_destroy();
    esp_camera_deinit();
    WIFIDestroy();

    vTaskDelay(3000 / portTICK_PERIOD_MS);
    esp_restart();      // Reset type: CPU reset (Reset both CPUs)

    vTaskDelay(5000 / portTICK_PERIOD_MS);
    hard_restart();     // Reset type: System reset (Triggered by watchdog), if esp_restart stalls (WDT needs to be activated)

    LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "Reboot failed!");
    vTaskDelete(NULL); //Delete this task if it comes to this point
}


void doReboot()
{
    LogFile.WriteToFile(ESP_LOG_INFO, TAG, "Reboot triggered by Software (5s)");
    LogFile.WriteToFile(ESP_LOG_WARN, TAG, "Reboot in 5sec");

    BaseType_t xReturned = xTaskCreate(&task_reboot, "task_reboot", configMINIMAL_STACK_SIZE * 4, (void*) true, 10, NULL);
    if( xReturned != pdPASS )
    {
        LogFile.WriteToFile(ESP_LOG_ERROR, TAG, "task_reboot not created -> force reboot without killing flow");
        task_reboot((void*) false);
    }
    vTaskDelay(10000 / portTICK_PERIOD_MS); // Prevent serving web client fetch response until system is shuting down
}


void doRebootOTA()
{
    LogFile.WriteToFile(ESP_LOG_WARN, TAG, "Reboot in 5sec");

    Camera.LightOnOff(false);
    StatusLEDOff();
    esp_camera_deinit();

    vTaskDelay(5000 / portTICK_PERIOD_MS);
    esp_restart();      // Reset type: CPU reset (Reset both CPUs)

    vTaskDelay(5000 / portTICK_PERIOD_MS);
    hard_restart();     // Reset type: System reset (Triggered by watchdog), if esp_restart stalls (WDT needs to be activated)
}


esp_err_t handler_reboot(httpd_req_t *req)
{
    #ifdef DEBUG_DETAIL_ON     
        LogFile.WriteHeapInfo("handler_reboot - Start");
    #endif    

    LogFile.WriteToFile(ESP_LOG_DEBUG, TAG, "handler_reboot");
    LogFile.WriteToFile(ESP_LOG_INFO, TAG, "!!! System will restart within 5 sec!!!");

    std::string response = 
        "<html><head><script>"
            "function m(h) {"
                "document.getElementById('t').innerHTML=h;"
                "setInterval(function (){h +='.'; document.getElementById('t').innerHTML=h;"
                "fetch('reboot_page.html',{mode: 'no-cors'}).then(r=>{parent.location.href=('index.html');})}, 1000);"
            "}</script></head></html><body style='font-family: arial'><h3 id=t></h3>"
            "<script>m('Rebooting!<br>The page will automatically reload in around 25..60s.<br><br>');</script>"
            "</body></html>";

    httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
    httpd_resp_send(req, response.c_str(), strlen(response.c_str()));
    
    doReboot();

    #ifdef DEBUG_DETAIL_ON 
        LogFile.WriteHeapInfo("handler_reboot - Done");    
    #endif

    return ESP_OK;
}


// Managed staging is an explicitly requested background operation. The upload
// location is fixed; request text selects only its expected manifest identity.
static portMUX_TYPE bundleJobMux=portMUX_INITIALIZER_UNLOCKED;
struct BundleStageJob {bool active=false,install=false,bootSelected=false;char id[65]{};const char* status="idle";};
static BundleStageJob bundleStageJob;
static void bundleStageWorker(void*) {
    portENTER_CRITICAL(&bundleJobMux);
    const auto job=bundleStageJob;
    portEXIT_CRITICAL(&bundleJobMux);
    if(job.install){
        const bool selected=installManagedBundle(job.id);
        portENTER_CRITICAL(&bundleJobMux);
        bundleStageJob.bootSelected=selected;
        bundleStageJob.status=selected?"boot_selected_reboot_required":"install_failed_or_uncertain";
        bundleStageJob.active=false;
        portEXIT_CRITICAL(&bundleJobMux);
        vTaskDelete(nullptr);
        return;
    }
    const auto result=stageManagedBundle("/sdcard/firmware/managed-bundle.zip",job.id);
    const char* status="rejected";
    switch(result){
    case MeterBundle::StageResult::Staged:status="staged";break;
    case MeterBundle::StageResult::Existing:status="already_staged";break;
    case MeterBundle::StageResult::Conflict:status="busy_or_staging_conflict";break;
    case MeterBundle::StageResult::IoError:status="storage_error";break;
    default:break;
    }
    portENTER_CRITICAL(&bundleJobMux);
    bundleStageJob.status=status;bundleStageJob.active=false;
    portEXIT_CRITICAL(&bundleJobMux);
    vTaskDelete(nullptr);
}
static esp_err_t bundleResponse(httpd_req_t* req,const char* code,const char* status){
    httpd_resp_set_status(req,code);httpd_resp_set_type(req,"application/json");
    httpd_resp_set_hdr(req,"Cache-Control","no-store");
    const std::string body=std::string("{\"status\":\"")+status+"\"}";
    return httpd_resp_send(req,body.c_str(),body.size());
}
static esp_err_t handle_bundle_action(httpd_req_t* req,bool install){
    if(!basic_auth_configured())return bundleResponse(req,"403 Forbidden","authentication_must_be_configured");
    char action[8]{};
    if(httpd_req_get_hdr_value_str(req,"X-Meter-Bundle-Action",action,sizeof(action))!=ESP_OK ||
       std::strcmp(action,install?"install":"stage")!=0 || req->content_len!=64 || httpd_req_get_url_query_len(req))
        return bundleResponse(req,"400 Bad Request","expected_action_header_and_64_byte_bundle_id");
    char id[65]{};size_t received=0;
    while(received<64){const int n=httpd_req_recv(req,id+received,64-received);
        if(n<=0)return bundleResponse(req,"400 Bad Request","incomplete_bundle_id");
        received+=n;
    }
    if(!MeterBundle::hashValid(std::string(id,64)))return bundleResponse(req,"400 Bad Request","invalid_bundle_id");
    portENTER_CRITICAL(&bundleJobMux);
    const bool busy=bundleStageJob.active;
    const bool staged=std::strcmp(bundleStageJob.id,id)==0 &&
        (std::strcmp(bundleStageJob.status,"staged")==0 || std::strcmp(bundleStageJob.status,"already_staged")==0);
    const bool selected=bundleStageJob.bootSelected;
    if(!busy && !selected && (!install || staged)){
        bundleStageJob.active=true;bundleStageJob.install=install;
        std::memcpy(bundleStageJob.id,id,65);bundleStageJob.status="queued_or_running";
    }
    portEXIT_CRITICAL(&bundleJobMux);
    if(busy)return bundleResponse(req,"409 Conflict","bundle_operation_active");
    if(selected)return bundleResponse(req,"409 Conflict","boot_already_selected");
    if(install && !staged)return bundleResponse(req,"409 Conflict","stage_matching_bundle_first");
    if(xTaskCreate(bundleStageWorker,"bundle_stage",24576,nullptr,1,nullptr)!=pdPASS){
        portENTER_CRITICAL(&bundleJobMux);
        bundleStageJob.active=false;bundleStageJob.status="task_creation_failed";
        portEXIT_CRITICAL(&bundleJobMux);
        return bundleResponse(req,"503 Service Unavailable","task_creation_failed");
    }
    return bundleResponse(req,"202 Accepted","accepted");
}
static esp_err_t handler_bundle_stage(httpd_req_t* req){return handle_bundle_action(req,false);}
static esp_err_t handler_bundle_install(httpd_req_t* req){return handle_bundle_action(req,true);}
static esp_err_t handler_bundle_status(httpd_req_t* req){
    if(!basic_auth_configured())return bundleResponse(req,"403 Forbidden","authentication_must_be_configured");
    portENTER_CRITICAL(&bundleJobMux);const auto job=bundleStageJob;portEXIT_CRITICAL(&bundleJobMux);
    const auto& running=MeterBundle::bootSelection();
    const bool verified=running.state()==MeterBundle::SelectionState::Selected;
    const std::string runningId=verified?running.id():"";
    const std::string body=std::string("{\"running_bundle_id\":\"")+runningId+
        "\",\"running_bundle_verified\":"+(verified?"true":"false")+
        ",\"active\":"+(job.active?"true":"false")+
        ",\"bundle_id\":\""+job.id+"\",\"status\":\""+job.status+"\",\"installed\":false,\"boot_selected\":"+(job.bootSelected?"true":"false")+"}";
    httpd_resp_set_type(req,"application/json");httpd_resp_set_hdr(req,"Cache-Control","no-store");
    return httpd_resp_send(req,body.c_str(),body.size());
}

void register_server_ota_sdcard_uri(httpd_handle_t server)
{
    ESP_LOGI(TAG, "Registering URI handlers");
    httpd_uri_t stageUri{};
    stageUri.uri="/bundle_stage";stageUri.method=HTTP_POST;
    stageUri.handler=APPLY_BASIC_AUTH_FILTER(handler_bundle_stage);
    if(httpd_register_uri_handler(server,&stageUri)!=ESP_OK)
        LogFile.WriteToFile(ESP_LOG_ERROR,TAG,"Could not register bundle staging endpoint");
    stageUri.uri="/bundle_install";stageUri.method=HTTP_POST;
    stageUri.handler=APPLY_BASIC_AUTH_FILTER(handler_bundle_install);
    if(httpd_register_uri_handler(server,&stageUri)!=ESP_OK)
        LogFile.WriteToFile(ESP_LOG_ERROR,TAG,"Could not register bundle installation endpoint");
    stageUri.uri="/bundle_status";stageUri.method=HTTP_GET;
    stageUri.handler=APPLY_BASIC_AUTH_FILTER(handler_bundle_status);
    if(httpd_register_uri_handler(server,&stageUri)!=ESP_OK)
        LogFile.WriteToFile(ESP_LOG_ERROR,TAG,"Could not register bundle status endpoint");

    
    httpd_uri_t camuri = { };
    camuri.method    = HTTP_GET;
    camuri.uri       = "/ota";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_ota_update);
    camuri.user_ctx  = (void*) "Do OTA";    
    httpd_register_uri_handler(server, &camuri);

    camuri.method    = HTTP_GET;
    camuri.uri       = "/reboot";
    camuri.handler = APPLY_BASIC_AUTH_FILTER(handler_reboot);
    camuri.user_ctx  = (void*) "Reboot";    
    httpd_register_uri_handler(server, &camuri);

}
