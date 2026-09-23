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
static std::atomic<int> scan_state{0}; // 1 scanning, 2 results ready, -1 failed
static wifi_ap_record_t scan_records[24];
static uint16_t scan_count=0;
static SemaphoreHandle_t setup_lock;
struct SetupGuard { SetupGuard(){xSemaphoreTake(setup_lock,portMAX_DELAY);} ~SetupGuard(){xSemaphoreGive(setup_lock);} };
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
 return phase>0?3:2;
}
static bool supported_ap(const wifi_ap_record_t& ap){
 return ap.authmode==WIFI_AUTH_OPEN||ap.authmode==WIFI_AUTH_WPA_PSK||ap.authmode==WIFI_AUTH_WPA2_PSK||ap.authmode==WIFI_AUTH_WPA_WPA2_PSK||ap.authmode==WIFI_AUTH_WPA2_WPA3_PSK;
}
static const char* description(int n) {
 switch(n){case 0:return "Ready for Wi-Fi setup";case 1:return "Connecting to Wi-Fi";case 2:return "Downloading AIEdge";case 3:return "Verifying package and SD files";case 4:return "Installing verified firmware";case 5:return "Installed. Restarting; open the device address below";case 6:return "Setting the clock for secure download";
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
static void download_failure(const std::string& message){SetupGuard guard;download_error=message;printf("AIEdge download: %s\n",message.c_str());}
static bool fetch_package() {
 {SetupGuard guard;download_error.clear();downloaded=0;download_progress.begin(uint32_t(esp_timer_get_time()/1000));}
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
 ImageArchive::Sha256 hash;unsigned char buffer[4096];unsigned count=0;int64_t start=esp_timer_get_time(),last_data=start;
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
 MeterBundle::File expected;expected.bytes=PACKAGE_BYTES;expected.hash=PACKAGE_SHA256;
 return MeterBundle::verifyFile<ImageArchive::Sha256>("/sdcard/aiedge-download.zip",expected);
}
static bool install_package() {
 auto stage=MeterBundle::stageZip<ImageArchive::Sha256>("/sdcard/aiedge-download.zip","/sdcard/bundles",PACKAGE_BUNDLE,PACKAGE_MODEL);
 if(stage!=MeterBundle::StageResult::Staged&&stage!=MeterBundle::StageResult::Existing)return false;
 MeterBundle::Manifest manifest;
 std::string object=std::string("/sdcard/bundles/objects/")+PACKAGE_BUNDLE;
 if(!MeterBundle::verify<ImageArchive::Sha256>(object,PACKAGE_BUNDLE,manifest).verified)return false;
 if(!AIEdge::seedSetupConfig("/sdcard",device_hostname)){phase=-5;return false;}
 if(!save_wifi()){phase=-5;return false;}
 phase=4;
 const auto* target=esp_ota_get_next_update_partition(nullptr);
 esp_ota_handle_t handle=0;
 FILE* f=fopen((object+"/firmware/firmware.bin").c_str(),"rb");if(!f)return false;
 if(!target||esp_ota_begin(target,manifest.firmware.bytes,&handle)!=ESP_OK){fclose(f);return false;}
 unsigned char buffer[4096];size_t count=0;bool ok=true;
 while(ok){size_t n=fread(buffer,1,sizeof buffer,f);if(n){ok=esp_ota_write(handle,buffer,n)==ESP_OK;count+=n;vTaskDelay(1);}if(n<sizeof buffer){if(ferror(f))ok=false;break;}}
 fclose(f);
 if(!ok||count!=manifest.firmware.bytes){esp_ota_abort(handle);return false;}
 if(esp_ota_end(handle)!=ESP_OK||digest_partition(target)!=manifest.appHash)return false;
 auto index=MeterBundle::prepareIndex<ImageArchive::Sha256>("/sdcard/bundles",PACKAGE_BUNDLE,digest_partition(esp_ota_get_running_partition()),PACKAGE_MODEL);
 if(index!=MeterBundle::IndexResult::Installed&&index!=MeterBundle::IndexResult::Existing)return false;
 if(esp_ota_set_boot_partition(target)!=ESP_OK)return false;
 const auto* selected=esp_ota_get_boot_partition();
 return selected&&selected->address==target->address;
}
static void worker(void*) {
 auto flags=xEventGroupWaitBits(wifi_events,1,pdFALSE,pdFALSE,pdMS_TO_TICKS(30000));
 if(!(flags&1)){phase=-2;if(serial_provisioning.exchange(false)){improv_error(3);improv_state(2);}vTaskDelete(nullptr);return;}
 // Save only credentials which obtained an IP, before download or provisioning success.
 if(!persist_connected_wifi()){phase=-8;if(serial_provisioning.exchange(false))improv_error(0xff);vTaskDelete(nullptr);return;}
 if(serial_provisioning.exchange(false)){improv_state(4);improv_send(AIEdgeImprov::result(1,{device_url()}));}
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
 phase=5;vTaskDelay(pdMS_TO_TICKS(4000));esp_restart();
}
static void wifi_event(void*,esp_event_base_t base,int32_t id,void* data) {
 if(base==IP_EVENT&&id==IP_EVENT_STA_GOT_IP)xEventGroupSetBits(wifi_events,1);
 if(base==WIFI_EVENT&&id==WIFI_EVENT_STA_DISCONNECTED)xEventGroupClearBits(wifi_events,1);
 if(base==WIFI_EVENT&&id==WIFI_EVENT_SCAN_DONE){
  SetupGuard guard;
  const auto* done=static_cast<wifi_event_sta_scan_done_t*>(data);
  scan_count=24;
  if(done&&done->status==0&&esp_wifi_scan_get_ap_records(&scan_count,scan_records)==ESP_OK)scan_state=2;
  else {esp_wifi_clear_ap_list();scan_count=0;scan_state=-1;}
 }
}

static esp_err_t home(httpd_req_t* req){httpd_resp_set_type(req,"text/html; charset=utf-8");httpd_resp_set_hdr(req,"Cache-Control","no-store");return httpd_resp_send(req,page,HTTPD_RESP_USE_STRLEN);}
static esp_err_t status(httpd_req_t* req){
 const int n=phase;
 cJSON* j=cJSON_CreateObject();if(!j)return ESP_ERR_NO_MEM;
 cJSON_AddNumberToObject(j,"phase",n);cJSON_AddStringToObject(j,"hostname",device_hostname.c_str());cJSON_AddStringToObject(j,"device_url",device_url().c_str());
 cJSON_AddStringToObject(j,"message",description(n));cJSON_AddBoolToObject(j,"wifi_connected",(xEventGroupGetBits(wifi_events)&1)!=0);cJSON_AddBoolToObject(j,"wifi_saved",wifi_saved);
 AIEdgeDownload::Progress snapshot;
 {SetupGuard guard;cJSON_AddStringToObject(j,"detail",download_error.c_str());snapshot=download_progress;}
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
 if(!sd_ready||phase>0||!AIEdgeImprov::validCredentials(name,pass))return false;
 if(scan_state==1){esp_wifi_scan_stop();scan_state=0;}
 ssid=name;password=pass;wifi_saved=false;phase=1;downloaded=0;download_progress={};download_error.clear();serial_provisioning=from_serial;xEventGroupClearBits(wifi_events,1);
 esp_wifi_disconnect();wifi_config_t cfg={};memcpy(cfg.sta.ssid,name.data(),name.size());memcpy(cfg.sta.password,pass.data(),pass.size());
 if(esp_wifi_set_config(WIFI_IF_STA,&cfg)!=ESP_OK||esp_wifi_connect()!=ESP_OK){phase=-2;serial_provisioning=false;return false;}
 if(from_serial)improv_state(3);
 if(xTaskCreate(worker,"download",16384,nullptr,4,nullptr)!=pdPASS){phase=-6;serial_provisioning=false;return false;}
 return true;
}
static bool begin_scan(){
 SetupGuard guard;
 if(phase>0)return false;
 if(scan_state==1)return true;
 scan_state=1;wifi_scan_config_t scan={};scan.show_hidden=false;
 if(esp_wifi_scan_start(&scan,false)!=ESP_OK){scan_state=-1;return false;}
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
 if(!sd_ready||phase>=0||phase==-8||!(xEventGroupGetBits(wifi_events)&1))return httpd_resp_send_err(req,HTTPD_400_BAD_REQUEST,"Reconnect Wi-Fi or wait for the current installation");
 phase=6;downloaded=0;download_progress={};download_error.clear();
 if(xTaskCreate(worker,"download",16384,nullptr,4,nullptr)!=pdPASS){phase=-6;return httpd_resp_send_err(req,HTTPD_500_INTERNAL_SERVER_ERROR,"Could not start installation");}
 return httpd_resp_send(req,"Retrying installation",HTTPD_RESP_USE_STRLEN);
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
 case 3:improv_send(AIEdgeImprov::result(3,{"AIEdge Wi-Fi loader","0.1.5-dev.20260922","ESP32",device_hostname}));break;
 case 4:
  if(begin_scan())serial_scan_pending=true;
  else improv_send(AIEdgeImprov::result(4,{}));
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
    {SetupGuard guard;if(scan_state==2)records.assign(scan_records,scan_records+scan_count);}
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
 gpio_set_direction(GPIO_NUM_4,GPIO_MODE_OUTPUT);gpio_set_level(GPIO_NUM_4,0);
 sdmmc_host_t host=SDMMC_HOST_DEFAULT();sdmmc_slot_config_t slot=SDMMC_SLOT_CONFIG_DEFAULT();slot.width=1;slot.flags|=SDMMC_SLOT_FLAG_INTERNAL_PULLUP;gpio_set_pull_mode(GPIO_NUM_13,GPIO_PULLUP_ONLY);
 esp_vfs_fat_sdmmc_mount_config_t cfg={};cfg.format_if_mount_failed=false;cfg.max_files=8;sdmmc_card_t* card=nullptr;
 sd_ready=esp_vfs_fat_sdmmc_mount("/sdcard",&host,&slot,&cfg,&card)==ESP_OK;if(!sd_ready)phase=-1;
 auto nvs=nvs_flash_init();if(nvs==ESP_ERR_NVS_NO_FREE_PAGES||nvs==ESP_ERR_NVS_NEW_VERSION_FOUND){ESP_ERROR_CHECK(nvs_flash_erase());nvs=nvs_flash_init();}ESP_ERROR_CHECK(nvs);
 ESP_ERROR_CHECK(esp_netif_init());ESP_ERROR_CHECK(esp_event_loop_create_default());esp_netif_create_default_wifi_ap();auto* sta=esp_netif_create_default_wifi_sta();ESP_ERROR_CHECK(esp_netif_set_hostname(sta,device_hostname.c_str()));wifi_events=xEventGroupCreate();
 wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();ESP_ERROR_CHECK(esp_wifi_init(&init));ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
 ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT,ESP_EVENT_ANY_ID,wifi_event,nullptr));ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,IP_EVENT_STA_GOT_IP,wifi_event,nullptr));
 wifi_config_t ap={};strcpy(reinterpret_cast<char*>(ap.ap.ssid),"AIEdge-Setup");strcpy(reinterpret_cast<char*>(ap.ap.password),"AIEdgeSetup");ap.ap.authmode=WIFI_AUTH_WPA2_PSK;ap.ap.max_connection=2;
 ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_APSTA));ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_AP,&ap));ESP_ERROR_CHECK(esp_wifi_start());
 httpd_config_t http=HTTPD_DEFAULT_CONFIG();http.stack_size=8192;http.max_open_sockets=4;http.lru_purge_enable=true;http.recv_wait_timeout=5;http.send_wait_timeout=5;httpd_handle_t server=nullptr;ESP_ERROR_CHECK(httpd_start(&server,&http));
 httpd_uri_t h={};h.uri="/";h.method=HTTP_GET;h.handler=home;ESP_ERROR_CHECK(httpd_register_uri_handler(server,&h));
 h.uri="/status";h.handler=status;ESP_ERROR_CHECK(httpd_register_uri_handler(server,&h));h.uri="/wifi";h.method=HTTP_POST;h.handler=credentials;ESP_ERROR_CHECK(httpd_register_uri_handler(server,&h));
 h.uri="/retry";h.handler=retry_install;ESP_ERROR_CHECK(httpd_register_uri_handler(server,&h));
 h.uri="/scan";h.handler=scan_start;ESP_ERROR_CHECK(httpd_register_uri_handler(server,&h));
 h.uri="/networks";h.method=HTTP_GET;h.handler=scan_results;ESP_ERROR_CHECK(httpd_register_uri_handler(server,&h));
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
 printf("AIEdge loader 0.1.5: hostname=%s.local; mDNS initialization=%s\n",device_hostname.c_str(),esp_err_to_name(discovery));
 std::string saved_name,saved_pass;
 if(read_saved_wifi(saved_name,saved_pass)){wifi_saved=true;if(sd_ready)begin_wifi(saved_name,saved_pass,false);}
}
