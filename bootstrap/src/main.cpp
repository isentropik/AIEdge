#include <cstdio>
#include <cstring>
#include <string>
#include <atomic>
#include <algorithm>
#include <ctime>
#include <sys/stat.h>
#include <unistd.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "driver/uart_vfs.h"
#include "freertos/semphr.h"
#include "ImprovSerial.h"
#include "WebsiteCredentialEsp.h"
#include "WebsiteHttp.h"
static AIEdgeAuth::NvsBackend websiteBackend;
static AIEdgeAuth::WebsiteAccess websiteAccess(websiteBackend);
static AIEdgeAuth::WebsiteHttp websiteHttp(websiteAccess);
#define WEBSITE_AUTH(handler) [](httpd_req_t* req){return websiteHttp.handle(req,handler);}
static esp_err_t website_setup(httpd_req_t* req){return websiteHttp.handle(req,[](httpd_req_t*){return ESP_FAIL;});}
#include "driver/sdmmc_host.h"
#include "esp_vfs_fat.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_http_server.h"
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include "esp_sntp.h"
#include "esp_ota_ops.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "esp_mac.h"
#include "DeviceIdentity.h"
#include "DownloadProgress.h"
#include "InstallConsent.h"
#include "CooperativeHash.h"
#include "InstallDiagnostics.h"
#include "esp_heap_caps.h"
#include "mdns.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "SavedWifi.h"
#include "cJSON.h"
#include "StageDeviceBundle.h"
#include "InstallBundleIndex.h"
#include "ImageArchiveSha.h"
#include "AIEdgeFirstBoot.h"
#include "package_pin.h"
#include "SetupPage.h"

// No camera, inference, MQTT or formatting in this application.
static std::atomic<int> phase{0}; // 0 ready, 1 connecting, 2 download, 3 verify, 4 flash, 5 complete, negatives errors
static std::atomic<unsigned> downloaded{0};
static AIEdgeDownload::Progress download_progress; // Protected by setup_lock.
static EventGroupHandle_t wifi_events;
static bool sd_ready=false;
static std::string ssid,password;
static std::string device_hostname;
static std::atomic<bool> wifi_saved{false};
static std::string download_error;
static std::string install_detail;
static std::atomic<int> scan_state{0}; // 1 scanning, 2 results ready, -1 failed
static wifi_ap_record_t scan_records[24];
static uint16_t scan_count=0;
static SemaphoreHandle_t setup_lock;
static SemaphoreHandle_t diagnostic_lock;
static AIEdgeSetup::InstallJournal journal;
static void diagnostic_record(const char* message){
 char line[256];snprintf(line,sizeof line,"[%lu ms] %s | free=%lu internal=%lu largest=%lu stack_min=%lu",
  (unsigned long)(esp_timer_get_time()/1000),message,(unsigned long)esp_get_free_heap_size(),
  (unsigned long)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
  (unsigned long)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
  (unsigned long)uxTaskGetStackHighWaterMark(nullptr));
 if(xSemaphoreTake(diagnostic_lock,pdMS_TO_TICKS(20))==pdTRUE){journal.append(line);xSemaphoreGive(diagnostic_lock);}
 printf("%s\n",line);
}
static void diagnostic_checkpoint(const char* step,const char* path,uint64_t offset){
 if(xSemaphoreTake(diagnostic_lock,pdMS_TO_TICKS(20))==pdTRUE){journal.current(step,path,offset,uint32_t(esp_timer_get_time()/1000));xSemaphoreGive(diagnostic_lock);}
 // Track every operation in RAM, but sample block messages to bound USB traffic.
 const bool block=!strcmp(step,"read.begin")||!strcmp(step,"hash.begin")||!strcmp(step,"block.done")||!strcmp(step,"extract.write")||!strcmp(step,"flash.write");
 if(block && offset%65536)return;
 char message[176];snprintf(message,sizeof message,"%s %s offset=%llu",step,path,(unsigned long long)offset);diagnostic_record(message);
}
static void diagnostic_task(void*){
 for(;;){vTaskDelay(pdMS_TO_TICKS(10000));if(phase<2||phase>6)continue;
  char message[208];bool ready=false;
  if(xSemaphoreTake(diagnostic_lock,pdMS_TO_TICKS(20))==pdTRUE){
   snprintf(message,sizeof message,"heartbeat phase=%d wifi=%d op_age_ms=%lu %.150s",int(phase),(xEventGroupGetBits(wifi_events)&1)!=0,
    (unsigned long)journal.age(uint32_t(esp_timer_get_time()/1000)),journal.active());ready=true;xSemaphoreGive(diagnostic_lock);
  }
  if(ready)diagnostic_record(message);
 }
}
struct SetupGuard { SetupGuard(){xSemaphoreTake(setup_lock,portMAX_DELAY);} ~SetupGuard(){xSemaphoreGive(setup_lock);} };
static void yield_to_system(){vTaskDelay(1);}
using LoaderSha=AIEdgeSetup::CooperativeHash<ImageArchive::Sha256,yield_to_system>;
static void installation_stage(const char* detail){
 {SetupGuard guard;install_detail=detail;}
 diagnostic_checkpoint("stage",detail,0);
}
static std::atomic<bool> serial_provisioning{false};
static bool serial_scan_pending=false;
static void improv_send(const AIEdgeImprov::Bytes& bytes){
 if(bytes.empty())return;
 uart_write_bytes(UART_NUM_0,bytes.data(),bytes.size());
}
static void improv_state(uint8_t state){improv_send(AIEdgeImprov::frame(1,{state}));}
static void improv_error(uint8_t error){improv_send(AIEdgeImprov::frame(2,{error}));}
static std::string device_url(){
 esp_netif_ip_info_t info{};auto* netif=esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
 if(netif&&esp_netif_get_ip_info(netif,&info)==ESP_OK&&info.ip.addr){char url[64];snprintf(url,sizeof url,"http://" IPSTR,IP2STR(&info.ip));return url;}
 return "http://"+device_hostname+".local";
}
static bool read_saved_wifi(std::string& name,std::string& pass){
 nvs_handle_t h;if(nvs_open("aiedge_setup",NVS_READONLY,&h)!=ESP_OK)return false;
 size_t size=0;auto err=nvs_get_blob(h,"wifi",nullptr,&size);
 if(err!=ESP_OK||size<3||size>97){nvs_close(h);return false;}
 AIEdgeImprov::Bytes bytes(size);err=nvs_get_blob(h,"wifi",bytes.data(),&size);nvs_close(h);
 return err==ESP_OK&&AIEdgeWifi::decode(bytes,name,pass);
}
static bool persist_connected_wifi(){
 std::string old_name,old_pass;
 if(read_saved_wifi(old_name,old_pass)&&old_name==ssid&&old_pass==password){wifi_saved=true;return true;}
 const auto bytes=AIEdgeWifi::encode(ssid,password);if(bytes.empty())return false;
 nvs_handle_t h;if(nvs_open("aiedge_setup",NVS_READWRITE,&h)!=ESP_OK)return false;
 auto err=nvs_set_blob(h,"wifi",bytes.data(),bytes.size());if(err==ESP_OK)err=nvs_commit(h);nvs_close(h);
 bool ok=err==ESP_OK&&read_saved_wifi(old_name,old_pass)&&old_name==ssid&&old_pass==password;
 wifi_saved=ok;return ok;
}
static uint8_t current_improv_state(){
 if(xEventGroupGetBits(wifi_events)&1)return 4;
 return phase==1?3:2;
}
static bool supported_ap(const wifi_ap_record_t& ap){
 return ap.authmode==WIFI_AUTH_OPEN||ap.authmode==WIFI_AUTH_WPA_PSK||ap.authmode==WIFI_AUTH_WPA2_PSK||ap.authmode==WIFI_AUTH_WPA_WPA2_PSK||ap.authmode==WIFI_AUTH_WPA2_WPA3_PSK;
}
static const char* description(int n) {
 switch(n){case 0:return "Ready for Wi-Fi setup";case 1:return "Connecting to Wi-Fi";case 2:return "Downloading AIEdge to device";case 3:return "Verifying package and SD files";case 4:return "Installing verified firmware";case 5:return "Installed. Restarting; AIEdge will open when ready";case 6:return "Setting the clock for secure download";case AIEdgeSetup::readyToInstall:return "Ready to download to device and install";
 case -1:return "SD card could not mount; nothing formatted";case -2:return "Wi-Fi connection failed";case -3:return "Package download failed; check Internet access and retry";case -4:return "Package verification failed";case -5:return "Could not save initial configuration";case -6:return "Firmware installation failed; loader retained";case -7:return "Could not synchronize time; check Internet access and retry";case -8:return "Wi-Fi connected, but saving credentials failed. Settings will not survive a restart.";default:return "Setup error";}
}
static std::string digest_partition(const esp_partition_t* p) {
 unsigned char hash[32];if(!p||esp_partition_get_sha256(p,hash)!=ESP_OK)return "";
 char out[65];for(int i=0;i<32;++i)sprintf(out+i*2,"%02x",hash[i]);return out;
}
static bool save_wifi() {
 const char* path="/sdcard/wlan.ini";struct stat st{};
 std::string data="ssid = \""+ssid+"\"\npassword = \""+password+"\"\nhostname = \""+device_hostname+"\"\n";
 if(stat(path,&st)==0){ // Retry only with exactly the saved configuration.
  FILE* old=fopen(path,"rb");if(!old)return false;char bytes[256];
  size_t n=fread(bytes,1,sizeof bytes,old);bool same=!ferror(old)&&n==data.size()&&!memcmp(bytes,data.data(),n);fclose(old);return same;
 }
 FILE* f=fopen("/sdcard/aiedge-wlan.pending","wb");if(!f)return false;
 bool ok=fwrite(data.data(),1,data.size(),f)==data.size();
 if(fflush(f)!=0||fsync(fileno(f))!=0)ok=false;
 if(fclose(f)!=0)ok=false;
 if(!ok)return false;
 FILE* check=fopen("/sdcard/aiedge-wlan.pending","rb");if(!check)return false;
 char b[256];size_t count=fread(b,1,sizeof b,check);ok=!ferror(check)&&count==data.size()&&!memcmp(b,data.data(),count);fclose(check);
 return ok&&rename("/sdcard/aiedge-wlan.pending",path)==0;
}
static bool release_url(const std::string& url){
 return url.size()<=AIEdgeIdentity::maxReleaseUrlBytes&&(url.rfind("https://github.com/",0)==0||url.rfind("https://release-assets.githubusercontent.com/",0)==0||url.rfind("https://objects.githubusercontent.com/",0)==0);
}
static esp_err_t download_event(esp_http_client_event_t* event){
 if(event->event_id==HTTP_EVENT_ON_HEADER&&event->header_key&&event->header_value&&!strcasecmp(event->header_key,"Location")){
  auto* location=static_cast<std::string*>(event->user_data);if(strlen(event->header_value)<=AIEdgeIdentity::maxReleaseUrlBytes)*location=event->header_value;
 }return ESP_OK;
}
static void download_failure(const std::string& message){{SetupGuard guard;download_error=message;}diagnostic_record(message.c_str());}
static bool fetch_package() {
 {SetupGuard guard;download_error.clear();install_detail.clear();downloaded=0;download_progress.begin(uint32_t(esp_timer_get_time()/1000));}
 std::string url=PACKAGE_URL,location;esp_http_client_handle_t client=nullptr;bool ok=false;
 for(int attempt=0;attempt<4;++attempt){
  if(!release_url(url))break;
  esp_http_client_config_t cfg={};cfg.url=url.c_str();cfg.timeout_ms=10000;cfg.disable_auto_redirect=true;cfg.buffer_size=4096;cfg.buffer_size_tx=AIEdgeIdentity::httpRequestBufferBytes;cfg.crt_bundle_attach=esp_crt_bundle_attach;cfg.event_handler=download_event;cfg.user_data=&location;
  location.clear();client=esp_http_client_init(&cfg);if(!client)break;
  auto opened=esp_http_client_open(client,0);
  if(opened==ESP_OK){
   const auto size=esp_http_client_fetch_headers(client);const int status=esp_http_client_get_status_code(client);
   if(status==200&&size==PACKAGE_BYTES){ok=true;break;}
   const bool redirect=status==301||status==302||status==303||status==307||status==308;
   esp_http_client_close(client);esp_http_client_cleanup(client);client=nullptr;
   if(!redirect||!release_url(location)){download_failure("HTTP "+std::to_string(status)+", length "+std::to_string(size)+" (expected "+std::to_string(PACKAGE_BYTES)+")");break;}
   url=location;
  }else{download_failure(std::string("Connection failed: ")+esp_err_to_name(opened)+", errno "+std::to_string(esp_http_client_get_errno(client)));esp_http_client_cleanup(client);client=nullptr;break;}
 }
 FILE* f=ok?fopen("/sdcard/aiedge-download.zip","wb"):nullptr;if(ok&&!f){download_failure("Could not open SD download file");ok=false;}
 LoaderSha hash;unsigned char buffer[4096];unsigned count=0;int64_t start=esp_timer_get_time(),last_data=start;
 while(ok&&count<PACKAGE_BYTES){
  const int64_t now=esp_timer_get_time();
  const auto limit=AIEdgeDownload::timeout(uint32_t((now-start)/1000),uint32_t((now-last_data)/1000));
  if(limit!=AIEdgeDownload::Timeout::None){download_failure(limit==AIEdgeDownload::Timeout::Stalled?"No download data received for 30 seconds":"Download exceeded 10 minutes");ok=false;break;}
  int n=esp_http_client_read(client,reinterpret_cast<char*>(buffer),sizeof buffer);
  if(n==-ESP_ERR_HTTP_EAGAIN){vTaskDelay(1);continue;}
  if(n<=0||count+(unsigned)n>PACKAGE_BYTES){download_failure("Download interrupted at "+std::to_string(count)+" bytes; read result "+std::to_string(n));ok=false;break;}
  ok=hash.update(buffer,n)&&fwrite(buffer,1,n,f)==(size_t)n;
  if(!ok){download_failure("Could not hash or save the downloaded data to SD");break;}
  count+=n;downloaded=count;last_data=esp_timer_get_time();
  {SetupGuard guard;download_progress.received(count,uint32_t(esp_timer_get_time()/1000));}
  vTaskDelay(1);
 }
 if(f){if(fflush(f)!=0||fsync(fileno(f))!=0)ok=false;if(fclose(f)!=0)ok=false;}
 if(client){esp_http_client_close(client);esp_http_client_cleanup(client);}
 if(!ok)return false;
 if(count!=PACKAGE_BYTES||hash.finish()!=PACKAGE_SHA256){download_failure("Package size or SHA-256 did not match; installation blocked");return false;}
 phase=3;installation_stage("Checking the downloaded package on SD");
 MeterBundle::File expected;expected.bytes=PACKAGE_BYTES;expected.hash=PACKAGE_SHA256;
 return MeterBundle::verifyFile<LoaderSha>("/sdcard/aiedge-download.zip",expected,diagnostic_checkpoint);
}
static bool install_package() {
 installation_stage("Unpacking and checking SD files");
 auto stage=MeterBundle::stageZip<LoaderSha>("/sdcard/aiedge-download.zip","/sdcard/bundles",PACKAGE_BUNDLE,PACKAGE_MODEL,diagnostic_checkpoint);
 if(stage!=MeterBundle::StageResult::Staged&&stage!=MeterBundle::StageResult::Existing){download_failure("SD package staging failed (code "+std::to_string(static_cast<int>(stage))+")");return false;}
 MeterBundle::Manifest manifest;
 std::string object=std::string("/sdcard/bundles/objects/")+PACKAGE_BUNDLE;
 installation_stage("Verifying the installed SD files");
 if(!MeterBundle::verify<LoaderSha>(object,PACKAGE_BUNDLE,manifest,diagnostic_checkpoint).verified)return false;
 installation_stage("Saving initial device settings");
 if(!AIEdge::seedSetupConfig("/sdcard",device_hostname)){phase=-5;return false;}
 if(!save_wifi()){phase=-5;return false;}
 phase=4;
 installation_stage("Writing verified firmware to the inactive partition");
 const auto* target=esp_ota_get_next_update_partition(nullptr);
 esp_ota_handle_t handle=0;
 FILE* f=fopen((object+"/firmware/firmware.bin").c_str(),"rb");if(!f)return false;
 diagnostic_checkpoint("flash.begin","inactive partition",0);
 if(!target||esp_ota_begin(target,manifest.firmware.bytes,&handle)!=ESP_OK){fclose(f);return false;}
 // Keep the flash transfer buffer off the stack shared with ZIP opening.
 std::unique_ptr<unsigned char[]> buffer(new(std::nothrow) unsigned char[4096]);
 if(!buffer){fclose(f);esp_ota_abort(handle);return false;}
 size_t count=0;bool ok=true;
 while(ok){diagnostic_checkpoint("read.begin","firmware.bin",count);size_t n=fread(buffer.get(),1,4096,f);if(n){diagnostic_checkpoint("flash.write","inactive partition",count);ok=esp_ota_write(handle,buffer.get(),n)==ESP_OK;count+=n;vTaskDelay(1);}if(n<4096){if(ferror(f))ok=false;break;}}
 fclose(f);
 if(!ok||count!=manifest.firmware.bytes){esp_ota_abort(handle);return false;}
 diagnostic_checkpoint("flash.verify","inactive partition",count);
 if(esp_ota_end(handle)!=ESP_OK||digest_partition(target)!=manifest.appHash)return false;
 installation_stage("Verifying firmware and preparing startup");
 auto index=MeterBundle::prepareIndex<LoaderSha>("/sdcard/bundles",PACKAGE_BUNDLE,digest_partition(esp_ota_get_running_partition()),PACKAGE_MODEL);
 if(index!=MeterBundle::IndexResult::Installed&&index!=MeterBundle::IndexResult::Existing)return false;
 if(esp_ota_set_boot_partition(target)!=ESP_OK)return false;
 const auto* selected=esp_ota_get_boot_partition();
 return selected&&selected->address==target->address;
}
static void wifi_worker(void*) {
 auto flags=xEventGroupWaitBits(wifi_events,1,pdFALSE,pdFALSE,pdMS_TO_TICKS(30000));
 if(!(flags&1)){phase=-2;if(serial_provisioning.exchange(false)){improv_error(3);improv_state(2);}vTaskDelete(nullptr);return;}
 // Save only credentials which obtained an IP, before download or provisioning success.
 if(!persist_connected_wifi()){phase=-8;if(serial_provisioning.exchange(false))improv_error(0xff);vTaskDelete(nullptr);return;}
 phase=AIEdgeSetup::readyToInstall;
 if(serial_provisioning.exchange(false)){improv_state(4);improv_send(AIEdgeImprov::result(1,{device_url()}));}
 vTaskDelete(nullptr);
}
// Called only by an explicit installation request, never by Wi-Fi connection.
static void install_worker(void*) {
 installation_stage("Starting the requested installation");
 phase=6;
 if(time(nullptr)<1700000000){
  if(!esp_sntp_enabled()){esp_sntp_setoperatingmode(SNTP_OPMODE_POLL);esp_sntp_setservername(0,"pool.ntp.org");esp_sntp_init();}
  for(int i=0;i<60&&time(nullptr)<1700000000;++i)vTaskDelay(pdMS_TO_TICKS(500));
  if(time(nullptr)<1700000000){phase=-7;vTaskDelete(nullptr);return;}
 }
 phase=2;
 if(!fetch_package()){phase=-3;vTaskDelete(nullptr);return;}
 phase=3;
 if(!install_package()){if(phase>=0)phase=-6;vTaskDelete(nullptr);return;}
 phase=5;diagnostic_record("installation complete; restart requested");vTaskDelay(pdMS_TO_TICKS(4000));esp_restart();
}
static void wifi_event(void*,esp_event_base_t base,int32_t id,void* data) {
 if(base==IP_EVENT&&id==IP_EVENT_STA_GOT_IP)xEventGroupSetBits(wifi_events,1);
 if(base==WIFI_EVENT&&id==WIFI_EVENT_STA_DISCONNECTED)xEventGroupClearBits(wifi_events,1);
 if(base==WIFI_EVENT&&id==WIFI_EVENT_SCAN_DONE){
  SetupGuard guard;
  if(scan_state!=1)return; // Ignore completion after a cancelled/timed-out scan.
  const auto* done=static_cast<wifi_event_sta_scan_done_t*>(data);
  scan_count=24;
  if(done&&done->status==0&&esp_wifi_scan_get_ap_records(&scan_count,scan_records)==ESP_OK)scan_state=2;
  else {esp_wifi_clear_ap_list();scan_count=0;scan_state=-1;}
 }
}

static esp_err_t home(httpd_req_t* req){httpd_resp_set_type(req,"text/html; charset=utf-8");httpd_resp_set_hdr(req,"Cache-Control","no-store");return httpd_resp_send(req,page,HTTPD_RESP_USE_STRLEN);}
static esp_err_t debug_log(httpd_req_t* req){
 if(xSemaphoreTake(diagnostic_lock,pdMS_TO_TICKS(20))!=pdTRUE)return httpd_resp_send_err(req,HTTPD_500_INTERNAL_SERVER_ERROR,"Debug log busy; try again");
 std::string text=journal.snapshot();xSemaphoreGive(diagnostic_lock);
 httpd_resp_set_type(req,"text/plain; charset=utf-8");httpd_resp_set_hdr(req,"Cache-Control","no-store");
 httpd_resp_set_hdr(req,"Content-Disposition","attachment; filename=aiedge-loader-debug.txt");
 return httpd_resp_send(req,text.data(),text.size());
}
static esp_err_t status(httpd_req_t* req){
 const int n=phase;
 cJSON* j=cJSON_CreateObject();if(!j)return ESP_ERR_NO_MEM;
 cJSON_AddNumberToObject(j,"phase",n);cJSON_AddStringToObject(j,"hostname",device_hostname.c_str());cJSON_AddStringToObject(j,"device_url",device_url().c_str());
 cJSON_AddStringToObject(j,"message",description(n));cJSON_AddBoolToObject(j,"wifi_connected",(xEventGroupGetBits(wifi_events)&1)!=0);cJSON_AddBoolToObject(j,"wifi_saved",wifi_saved);
 cJSON_AddBoolToObject(j,"can_install",AIEdgeSetup::mayInstall(n,sd_ready,(xEventGroupGetBits(wifi_events)&1)!=0,wifi_saved));
 AIEdgeDownload::Progress snapshot;
 {SetupGuard guard;cJSON_AddStringToObject(j,"detail",download_error.empty()?install_detail.c_str():download_error.c_str());snapshot=download_progress;}
 const auto stats=AIEdgeDownload::view(snapshot,PACKAGE_BYTES,uint32_t(esp_timer_get_time()/1000),n==2);
 cJSON_AddNumberToObject(j,"downloaded_bytes",snapshot.bytes);cJSON_AddNumberToObject(j,"total_bytes",PACKAGE_BYTES);
 cJSON_AddNumberToObject(j,"progress",stats.percent);cJSON_AddNumberToObject(j,"elapsed_seconds",stats.elapsedSeconds);
 cJSON_AddNumberToObject(j,"average_bytes_per_second",stats.averageBytesPerSecond);cJSON_AddBoolToObject(j,"waiting_for_data",stats.waitingForData);
 if(stats.remainingSeconds>=0)cJSON_AddNumberToObject(j,"remaining_seconds",stats.remainingSeconds);else cJSON_AddNullToObject(j,"remaining_seconds");
 char* s=cJSON_PrintUnformatted(j);cJSON_Delete(j);if(!s)return ESP_ERR_NO_MEM;
 httpd_resp_set_type(req,"application/json");httpd_resp_set_hdr(req,"Cache-Control","no-store");
 const auto r=httpd_resp_send(req,s,HTTPD_RESP_USE_STRLEN);cJSON_free(s);return r;
}
// Both HTTP and USB provision through this one serialized operation.
static bool begin_wifi(const std::string& name,const std::string& pass,bool from_serial){
 SetupGuard guard;
 if(!sd_ready||!AIEdgeSetup::mayConfigureWifi(phase)||!AIEdgeImprov::validCredentials(name,pass))return false;
 if(scan_state==1){esp_wifi_scan_stop();scan_state=0;}
 ssid=name;password=pass;wifi_saved=false;phase=1;downloaded=0;download_progress={};download_error.clear();install_detail.clear();serial_provisioning=from_serial;xEventGroupClearBits(wifi_events,1);
 esp_wifi_disconnect();wifi_config_t cfg={};memcpy(cfg.sta.ssid,name.data(),name.size());memcpy(cfg.sta.password,pass.data(),pass.size());
 if(esp_wifi_set_config(WIFI_IF_STA,&cfg)!=ESP_OK||esp_wifi_connect()!=ESP_OK){phase=-2;serial_provisioning=false;return false;}
 if(from_serial)improv_state(3);
 if(xTaskCreate(wifi_worker,"wifi_setup",8192,nullptr,4,nullptr)!=pdPASS){phase=-2;serial_provisioning=false;return false;}
 return true;
}
static bool begin_scan(){
 SetupGuard guard;
 if(!AIEdgeSetup::mayConfigureWifi(phase)){diagnostic_record("Wi-Fi scan refused: device busy");return false;}
 if(scan_state==1)return true;
 scan_state=1;wifi_scan_config_t scan={};scan.show_hidden=false;
 const auto error=esp_wifi_scan_start(&scan,false);
 if(error!=ESP_OK){scan_state=-1;char message[96];snprintf(message,sizeof message,"Wi-Fi scan start failed: %s",esp_err_to_name(error));diagnostic_record(message);return false;}
 return true;
}
static esp_err_t credentials(httpd_req_t* req){
 if(req->content_len==0||req->content_len>512)return httpd_resp_send_err(req,HTTPD_400_BAD_REQUEST,"Invalid request size");
 char body[513];size_t got=0;while(got<req->content_len){int n=httpd_req_recv(req,body+got,req->content_len-got);if(n<=0)return ESP_FAIL;got+=n;}body[got]=0;
 if(strstr(body,"\\u0000")||memchr(body,0,got))return httpd_resp_send_err(req,HTTPD_400_BAD_REQUEST,"Invalid text");
 cJSON* j=cJSON_Parse(body);if(!j)return httpd_resp_send_err(req,HTTPD_400_BAD_REQUEST,"Invalid JSON");
 auto* a=cJSON_GetObjectItemCaseSensitive(j,"ssid");auto* b=cJSON_GetObjectItemCaseSensitive(j,"password");
 bool ok=cJSON_IsString(a)&&cJSON_IsString(b);std::string name=ok?a->valuestring:"",pass=ok?b->valuestring:"";
 cJSON_Delete(j);
 if(!ok||!AIEdgeImprov::validCredentials(name,pass))return httpd_resp_send_err(req,HTTPD_400_BAD_REQUEST,"Check Wi-Fi name and password lengths");
 if(!begin_wifi(name,pass,false))return httpd_resp_send_err(req,HTTPD_400_BAD_REQUEST,"Device busy, SD unavailable, or Wi-Fi setup failed");
 return httpd_resp_send(req,"Connecting",HTTPD_RESP_USE_STRLEN);
}
static esp_err_t retry_install(httpd_req_t* req){
 SetupGuard guard;
 if(!AIEdgeSetup::mayInstall(phase,sd_ready,(xEventGroupGetBits(wifi_events)&1)!=0,wifi_saved))return httpd_resp_send_err(req,HTTPD_400_BAD_REQUEST,"Connect and save Wi-Fi, or wait for the current installation");
 phase=6;downloaded=0;download_progress={};download_error.clear();install_detail.clear();
 if(xTaskCreate(install_worker,"download",16384,nullptr,4,nullptr)!=pdPASS){phase=-6;return httpd_resp_send_err(req,HTTPD_500_INTERNAL_SERVER_ERROR,"Could not start installation");}
 return httpd_resp_send(req,"Starting installation",HTTPD_RESP_USE_STRLEN);
}
static esp_err_t scan_start(httpd_req_t* req){
 if(!begin_scan())return httpd_resp_send_err(req,HTTPD_400_BAD_REQUEST,"Device busy or Wi-Fi scan failed");
 return httpd_resp_send(req,"Scanning",HTTPD_RESP_USE_STRLEN);
}
static void improv_command(const AIEdgeImprov::Bytes& data){
 AIEdgeImprov::Request req;
 if(!AIEdgeImprov::decode(data,req)){improv_error(1);return;}
 improv_error(0);
 switch(req.command){
 case 1:
  if(!begin_wifi(req.ssid,req.password,true)){improv_error(0xff);improv_state(current_improv_state());}
  break;
 case 2:
  improv_state(current_improv_state());
  if(current_improv_state()==4)improv_send(AIEdgeImprov::result(2,{device_url()}));
  break;
 case 3:improv_send(AIEdgeImprov::result(3,{"AIEdge Wi-Fi loader","0.1.10-dev.20260922","ESP32",device_hostname}));break;
 case 4:
  if(begin_scan())serial_scan_pending=true;
  else improv_error(0xff);
  break;
 default:improv_error(2);break;
 }
}
static void improv_task(void*){
 AIEdgeImprov::Parser parser;uint8_t bytes[128];int64_t last_input=0,scan_started=0;
 for(;;){
  int n=uart_read_bytes(UART_NUM_0,bytes,sizeof bytes,pdMS_TO_TICKS(50));
  if(n>0){
   if(esp_timer_get_time()-last_input>500000)parser.reset();
   for(int i=0;i<n;++i)parser.feed(bytes[i],improv_command,[]{improv_error(1);});
   last_input=esp_timer_get_time();
  }
  if(serial_scan_pending){
   if(!scan_started)scan_started=esp_timer_get_time();
   if(scan_state!=1||esp_timer_get_time()-scan_started>15000000){
    std::vector<wifi_ap_record_t> records;
    bool succeeded=false;
    {SetupGuard guard;
     succeeded=scan_state==2;
     if(succeeded)records.assign(scan_records,scan_records+scan_count);
     else if(scan_state==1){scan_state=-1;esp_wifi_scan_stop();esp_wifi_clear_ap_list();}
    }
    if(!succeeded){
     diagnostic_record("Wi-Fi scan failed, cancelled or timed out");
     improv_error(0xff);serial_scan_pending=false;scan_started=0;continue;
    }
    std::vector<std::string> sent;
    for(const auto& ap:records){
     std::string name(reinterpret_cast<const char*>(ap.ssid),strnlen(reinterpret_cast<const char*>(ap.ssid),32));
     if(!supported_ap(ap)||!AIEdgeImprov::validCredentials(name,"")||std::find(sent.begin(),sent.end(),name)!=sent.end())continue;
     sent.push_back(name);improv_send(AIEdgeImprov::result(4,{name,std::to_string(ap.rssi),ap.authmode==WIFI_AUTH_OPEN?"NO":"YES"}));
    }
    improv_send(AIEdgeImprov::result(4,{}));serial_scan_pending=false;scan_started=0;
   }
  }else scan_started=0;
 }
}
static esp_err_t scan_results(httpd_req_t* req){
 SetupGuard guard;
 const int state=scan_state;auto* root=cJSON_CreateObject();
 cJSON_AddNumberToObject(root,"state",state);auto* list=cJSON_AddArrayToObject(root,"networks");
 if(state==2)for(unsigned i=0;i<scan_count;++i){
  const auto& ap=scan_records[i];if(!ap.ssid[0])continue;
  auto* item=cJSON_CreateObject();char name[33];memcpy(name,ap.ssid,32);name[32]=0;
  cJSON_AddStringToObject(item,"ssid",name);cJSON_AddNumberToObject(item,"rssi",ap.rssi);
  cJSON_AddBoolToObject(item,"open",ap.authmode==WIFI_AUTH_OPEN);
  cJSON_AddBoolToObject(item,"supported",ap.authmode==WIFI_AUTH_OPEN||ap.authmode==WIFI_AUTH_WPA_PSK||ap.authmode==WIFI_AUTH_WPA2_PSK||ap.authmode==WIFI_AUTH_WPA_WPA2_PSK||ap.authmode==WIFI_AUTH_WPA2_WPA3_PSK);
  cJSON_AddItemToArray(list,item);
 }
 char* json=cJSON_PrintUnformatted(root);httpd_resp_set_type(req,"application/json");httpd_resp_set_hdr(req,"Cache-Control","no-store");
 auto result=httpd_resp_send(req,json,HTTPD_RESP_USE_STRLEN);cJSON_free(json);cJSON_Delete(root);return result;
}
extern "C" void app_main(){
 uint8_t station_mac[6];ESP_ERROR_CHECK(esp_read_mac(station_mac,ESP_MAC_WIFI_STA));device_hostname=AIEdgeIdentity::hostname(station_mac);
 setup_lock=xSemaphoreCreateMutex();configASSERT(setup_lock);
 diagnostic_lock=xSemaphoreCreateMutex();configASSERT(diagnostic_lock);
 char boot[96];snprintf(boot,sizeof boot,"loader=0.1.10 reset_reason=%d",int(esp_reset_reason()));diagnostic_record(boot);
 gpio_set_direction(GPIO_NUM_4,GPIO_MODE_OUTPUT);gpio_set_level(GPIO_NUM_4,0);
 sdmmc_host_t host=SDMMC_HOST_DEFAULT();sdmmc_slot_config_t slot=SDMMC_SLOT_CONFIG_DEFAULT();slot.width=1;slot.flags|=SDMMC_SLOT_FLAG_INTERNAL_PULLUP;gpio_set_pull_mode(GPIO_NUM_13,GPIO_PULLUP_ONLY);
 esp_vfs_fat_sdmmc_mount_config_t cfg={};cfg.format_if_mount_failed=false;cfg.max_files=8;sdmmc_card_t* card=nullptr;
 sd_ready=esp_vfs_fat_sdmmc_mount("/sdcard",&host,&slot,&cfg,&card)==ESP_OK;if(!sd_ready)phase=-1;
 auto nvs=nvs_flash_init();
 if(nvs!=ESP_OK){
  printf("AIEdge internal settings unavailable (%s); settings preserved. Use USB diagnostics.\n",esp_err_to_name(nvs));
  return; // Never erase Wi-Fi or website credentials as automatic recovery.
 }
 ESP_ERROR_CHECK(esp_netif_init());ESP_ERROR_CHECK(esp_event_loop_create_default());esp_netif_create_default_wifi_ap();auto* sta=esp_netif_create_default_wifi_sta();ESP_ERROR_CHECK(esp_netif_set_hostname(sta,device_hostname.c_str()));wifi_events=xEventGroupCreate();
 wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();ESP_ERROR_CHECK(esp_wifi_init(&init));ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
 ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT,ESP_EVENT_ANY_ID,wifi_event,nullptr));ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,IP_EVENT_STA_GOT_IP,wifi_event,nullptr));
 wifi_config_t ap={};strcpy(reinterpret_cast<char*>(ap.ap.ssid),"AIEdge-Setup");strcpy(reinterpret_cast<char*>(ap.ap.password),"AIEdgeSetup");ap.ap.authmode=WIFI_AUTH_WPA2_PSK;ap.ap.max_connection=2;
 ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA));ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP,&ap));ESP_ERROR_CHECK(esp_wifi_start());
 websiteHttp.initialize();
 httpd_config_t http=HTTPD_DEFAULT_CONFIG();http.max_uri_handlers=12;http.stack_size=8192;http.max_open_sockets=4;http.lru_purge_enable=true;http.recv_wait_timeout=5;http.send_wait_timeout=5;httpd_handle_t server=nullptr;ESP_ERROR_CHECK(httpd_start(&server,&http));
 httpd_uri_t h={};h.uri="/auth/setup";h.method=HTTP_POST;h.handler=website_setup;ESP_ERROR_CHECK(httpd_register_uri_handler(server,&h));
 h.method=HTTP_GET;ESP_ERROR_CHECK(httpd_register_uri_handler(server,&h));
 h.uri="/auth/password";h.method=HTTP_POST;ESP_ERROR_CHECK(httpd_register_uri_handler(server,&h));
 h.method=HTTP_GET;ESP_ERROR_CHECK(httpd_register_uri_handler(server,&h));
 h.uri="/";h.method=HTTP_GET;h.handler=WEBSITE_AUTH(home);ESP_ERROR_CHECK(httpd_register_uri_handler(server,&h));
 h.uri="/status";h.handler=WEBSITE_AUTH(status);ESP_ERROR_CHECK(httpd_register_uri_handler(server,&h));h.uri="/wifi";h.method=HTTP_POST;h.handler=WEBSITE_AUTH(credentials);ESP_ERROR_CHECK(httpd_register_uri_handler(server,&h));
 h.uri="/debug-log";h.method=HTTP_GET;h.handler=WEBSITE_AUTH(debug_log);ESP_ERROR_CHECK(httpd_register_uri_handler(server,&h));h.method=HTTP_POST;
 h.uri="/retry";h.handler=WEBSITE_AUTH(retry_install);ESP_ERROR_CHECK(httpd_register_uri_handler(server,&h));
 h.uri="/install";h.handler=WEBSITE_AUTH(retry_install);ESP_ERROR_CHECK(httpd_register_uri_handler(server,&h));
 h.uri="/scan";h.handler=WEBSITE_AUTH(scan_start);ESP_ERROR_CHECK(httpd_register_uri_handler(server,&h));
 h.uri="/networks";h.method=HTTP_GET;h.handler=WEBSITE_AUTH(scan_results);ESP_ERROR_CHECK(httpd_register_uri_handler(server,&h));
 // Advertise on the setup AP as well as the connected home network.
 // Name discovery is optional: keep the IP setup page working if it fails.
 esp_err_t discovery=mdns_init();
 if(discovery==ESP_OK)discovery=mdns_hostname_set(device_hostname.c_str());
 if(discovery==ESP_OK)discovery=mdns_instance_name_set("AIEdge setup");
 if(discovery==ESP_OK)discovery=mdns_service_add(nullptr,"_http","_tcp",80,nullptr,0);
 if(discovery==ESP_OK)printf("AIEdge setup name discovery ready: http://%s.local\n",device_hostname.c_str());
 else printf("AIEdge name discovery unavailable (%s); use http://192.168.4.1\n",esp_err_to_name(discovery));
 uart_config_t serial_cfg={};serial_cfg.baud_rate=115200;serial_cfg.data_bits=UART_DATA_8_BITS;serial_cfg.parity=UART_PARITY_DISABLE;serial_cfg.stop_bits=UART_STOP_BITS_1;serial_cfg.flow_ctrl=UART_HW_FLOWCTRL_DISABLE;serial_cfg.source_clk=UART_SCLK_DEFAULT;
 if(uart_param_config(UART_NUM_0,&serial_cfg)==ESP_OK&&uart_driver_install(UART_NUM_0,2048,0,0,nullptr,0)==ESP_OK){
  uart_vfs_dev_use_driver(UART_NUM_0);
  if(xTaskCreate(improv_task,"improv",6144,nullptr,3,nullptr)!=pdPASS)printf("USB Wi-Fi setup unavailable; use the setup hotspot\n");
 }else printf("USB Wi-Fi setup unavailable; use the setup hotspot\n");
 printf("AIEdge Wi-Fi loader ready: AIEdge-Setup, http://192.168.4.1; SD=%s\n",sd_ready?"mounted":"failed");
 diagnostic_record(sd_ready?"SD mounted; setup ready":"SD mount failed");
 if(xTaskCreate(diagnostic_task,"install_log",4096,nullptr,2,nullptr)!=pdPASS)diagnostic_record("Could not start diagnostic heartbeat");
 printf("AIEdge loader 0.1.10: hostname=%s.local; mDNS initialization=%s\n",device_hostname.c_str(),esp_err_to_name(discovery));
 std::string saved_name,saved_pass;
 if(read_saved_wifi(saved_name,saved_pass)){wifi_saved=true;if(sd_ready)begin_wifi(saved_name,saved_pass,false);}
}
