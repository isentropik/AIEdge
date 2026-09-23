#include "StorageRecovery.h"
#include "basic_auth.h"
#include "RecoveryWifi.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "nvs.h"
#include "../components/esp-protocols/components/mdns/include/mdns.h"
#include "cJSON.h"
#include <cstdio>

namespace {
constexpr const char* TAG = "AIEdge recovery";
esp_netif_t* station = nullptr;
esp_timer_handle_t retryTimer = nullptr;
char hostname[20] = {};
bool savedWifi = false;
bool nvsReady = false;

constexpr char page[] = R"HTML(<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AIEdge — storage unavailable</title>
<style>:root{color-scheme:light dark;--bg:#f3f6f7;--card:#fff;--text:#182b34;--line:#bbc9cf}html[data-theme=dark]{--bg:#101c22;--card:#1b2c35;--text:#e7f0f3;--line:#536c79;color-scheme:dark}html[data-theme=light]{color-scheme:light}@media(prefers-color-scheme:dark){html:not([data-theme=light]){--bg:#101c22;--card:#1b2c35;--text:#e7f0f3;--line:#536c79}}*{box-sizing:border-box}body{margin:0;padding:24px;background:var(--bg);color:var(--text);font:16px/1.55 system-ui,sans-serif}main{max-width:720px;margin:24px auto;padding:28px;background:var(--card);border-radius:18px}header{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}h1{margin:0}h2{font-size:1.35rem;margin-top:28px}select{padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:inherit}p{margin:14px 0}.muted{font-size:.9rem}li{margin:10px 0}code{overflow-wrap:anywhere}</style>
<main><header><h1>AIEdge</h1><label>Theme <select id="theme"><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select></label></header>
<h2 id="heading">Storage unavailable</h2><p id="reason">AIEdge could not initialize storage. Checking details…</p><p>Meter readings, camera capture and saved settings pages are unavailable until storage is restored. This recovery page is stored in the firmware.</p>
<ol id="card-help"><li>Disconnect power before removing or inserting the card.</li><li>Check that the card is seated correctly. If needed, check it on a computer and preserve your files. AIEdge requires FAT32.</li><li>Reconnect power with the card installed.</li></ol>
<p>No card formatting or file deletion has been performed by recovery.</p><p id="network">Checking network status…</p><p class="muted">If saved Wi-Fi is unavailable, connect to <strong>AIEdge-Setup</strong> with password <code>AIEdgeSetup</code> and open <code>http://192.168.4.1</code>. Recovery provides status only; use the USB installer to configure Wi-Fi if necessary.</p></main>
<script>const t=document.getElementById('theme');function apply(v){document.documentElement.dataset.theme=v;t.value=v}try{apply(localStorage.getItem('aiedge-device-theme')||'system')}catch(e){apply('system')}t.onchange=()=>{apply(t.value);try{localStorage.setItem('aiedge-device-theme',t.value)}catch(e){}};async function status(){try{const r=await fetch('/recovery/status',{cache:'no-store'});if(!r.ok)throw Error();const s=await r.json();document.getElementById('heading').textContent=s.nvs_available?'SD card unavailable':'Saved settings unavailable';document.getElementById('reason').textContent=s.nvs_available?'AIEdge could not mount the SD card. It may be missing, unreadable or use an unsupported filesystem.':'Internal saved settings could not be opened. Existing settings have not been erased. Check the USB startup logs before resetting user data.';document.getElementById('card-help').hidden=!s.nvs_available;document.getElementById('network').textContent=s.ip?'Connected: '+s.ip+' · '+s.hostname+'.local':s.saved_wifi?'Reconnecting to saved Wi-Fi. The recovery hotspot remains available.':'No usable saved Wi-Fi found. The recovery hotspot is available.'}catch(e){document.getElementById('network').textContent='Device not responding. Check its power and network connection.'}}status();setInterval(status,15000);</script></html>)HTML";

esp_err_t pageHandler(httpd_req_t* req) {
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_send(req, page, sizeof(page) - 1);
}
esp_err_t statusHandler(httpd_req_t* req) {
    esp_netif_ip_info_t info = {};
    char ip[16] = {};
    wifi_ap_record_t ap = {};
    if (esp_wifi_sta_get_ap_info(&ap) == ESP_OK && esp_netif_get_ip_info(station, &info) == ESP_OK && info.ip.addr)
        snprintf(ip, sizeof ip, IPSTR, IP2STR(&info.ip));
    cJSON* json = cJSON_CreateObject();
    if (!json) return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Out of memory");
    cJSON_AddBoolToObject(json, "storage_available", false);
    cJSON_AddBoolToObject(json, "camera_available", false);
    cJSON_AddBoolToObject(json, "saved_wifi", savedWifi);
    cJSON_AddBoolToObject(json, "nvs_available", nvsReady);
    cJSON_AddStringToObject(json, "hostname", hostname);
    cJSON_AddStringToObject(json, "ip", ip);
    char* body = cJSON_PrintUnformatted(json);
    cJSON_Delete(json);
    if (!body) return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Out of memory");
    httpd_resp_set_type(req, "application/json");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    const auto result = httpd_resp_sendstr(req, body);
    cJSON_free(body);
    return result;
}
esp_err_t identityHandler(httpd_req_t* req) {
    char query[64] = {}, type[24] = {};
    if (httpd_req_get_url_query_str(req, query, sizeof query) != ESP_OK ||
        httpd_query_key_value(query, "type", type, sizeof type) != ESP_OK ||
        strcmp(type, "Hostname") != 0)
        return httpd_resp_send_err(req, HTTPD_404_NOT_FOUND, "Unavailable in storage recovery");
    httpd_resp_set_type(req, "text/plain");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    return httpd_resp_sendstr(req, hostname);
}
void retry(void*) { esp_wifi_connect(); }
void wifiEvent(void*, esp_event_base_t, int32_t id, void*) {
    if (!savedWifi) return;
    if (id == WIFI_EVENT_STA_START) esp_wifi_connect();
    else if (id == WIFI_EVENT_STA_DISCONNECTED && retryTimer) {
        esp_timer_stop(retryTimer);
        esp_timer_start_once(retryTimer, 15000000);
    }
}
bool check(esp_err_t result, const char* operation) {
    if (result == ESP_OK) return true;
    ESP_LOGE(TAG, "%s: %s", operation, esp_err_to_name(result));
    return false;
}
}

bool startStorageRecovery(bool nvsAvailable) {
    nvsReady = nvsAvailable;
    // Do not erase NVS or depend on wlan.ini, which is on the unavailable card.
    nvs_handle_t handle;
    char ssid[32] = {}, password[64] = {};
    if (nvsReady && nvs_open("aiedge_setup", NVS_READONLY, &handle) == ESP_OK) {
        uint8_t bytes[97]; size_t size = sizeof bytes;
        if (nvs_get_blob(handle, "wifi", bytes, &size) == ESP_OK)
            savedWifi = AIEdgeRecovery::decodeWifi(bytes, size, ssid, password);
        nvs_close(handle);
    }
    uint8_t mac[6];
    if (!check(esp_read_mac(mac, ESP_MAC_WIFI_STA), "Read identity")) return false;
    snprintf(hostname, sizeof hostname, "aiedge-%02x%02x%02x", mac[3], mac[4], mac[5]);
    if (!check(esp_netif_init(), "Network init") || !check(esp_event_loop_create_default(), "Event loop")) return false;
    station = esp_netif_create_default_wifi_sta();
    if (!station || !esp_netif_create_default_wifi_ap()) return false;
    esp_netif_set_hostname(station, hostname);
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    init.nvs_enable = false;
    if (!check(esp_wifi_init(&init), "Wi-Fi init") || !check(esp_wifi_set_storage(WIFI_STORAGE_RAM), "Wi-Fi RAM storage")) return false;
    esp_timer_create_args_t timer = {};
    timer.callback = retry; timer.name = "recovery-wifi";
    if (!check(esp_timer_create(&timer, &retryTimer), "Retry timer") ||
        !check(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifiEvent, nullptr), "Wi-Fi events")) return false;
    wifi_config_t sta = {}, ap = {};
    memcpy(sta.sta.ssid, ssid, sizeof ssid); memcpy(sta.sta.password, password, sizeof password);
    strcpy(reinterpret_cast<char*>(ap.ap.ssid), "AIEdge-Setup");
    strcpy(reinterpret_cast<char*>(ap.ap.password), "AIEdgeSetup");
    ap.ap.authmode = WIFI_AUTH_WPA2_PSK; ap.ap.max_connection = 2; ap.ap.channel = 1;
    if (!check(esp_wifi_set_mode(WIFI_MODE_APSTA), "Wi-Fi mode") ||
        !check(esp_wifi_set_config(WIFI_IF_AP, &ap), "Recovery hotspot") ||
        (savedWifi && !check(esp_wifi_set_config(WIFI_IF_STA, &sta), "Saved Wi-Fi")) ||
        !check(esp_wifi_start(), "Start Wi-Fi")) return false;
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.uri_match_fn = httpd_uri_match_wildcard; config.lru_purge_enable = true;
    config.recv_wait_timeout = 5; config.send_wait_timeout = 5;
    httpd_handle_t server = nullptr;
    if (!check(httpd_start(&server, &config), "Recovery server")) return false;
    init_basic_auth();
    if (!check(register_website_auth(server), "Website authentication")) { httpd_stop(server); return false; }
    httpd_uri_t status = {}; status.uri = "/recovery/status"; status.method = HTTP_GET; status.handler = APPLY_BASIC_AUTH_FILTER(statusHandler);
    httpd_uri_t info = {}; info.uri = "/info"; info.method = HTTP_GET; info.handler = APPLY_BASIC_AUTH_FILTER(identityHandler);
    httpd_uri_t sysinfo = {}; sysinfo.uri = "/sysinfo"; sysinfo.method = HTTP_GET; sysinfo.handler = APPLY_BASIC_AUTH_FILTER(statusHandler);
    httpd_uri_t root = {}; root.uri = "/*"; root.method = HTTP_GET; root.handler = APPLY_BASIC_AUTH_FILTER(pageHandler);
    if (!check(httpd_register_uri_handler(server, &status), "Status route") ||
        !check(httpd_register_uri_handler(server, &info), "Identity route") ||
        !check(httpd_register_uri_handler(server, &sysinfo), "System status route") ||
        !check(httpd_register_uri_handler(server, &root), "Recovery route")) return false;
    start_website_usb(server);
    if (mdns_init() == ESP_OK) {
        mdns_hostname_set(hostname); mdns_instance_name_set("AIEdge recovery");
        mdns_service_add(nullptr, "_http", "_tcp", 80, nullptr, 0);
    }
    ESP_LOGW(TAG, "Storage unavailable; read-only recovery ready at http://%s.local or http://192.168.4.1 on AIEdge-Setup", hostname);
    return true;
}
