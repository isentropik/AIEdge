
#pragma once
#include <cstdint>
using esp_http_client_handle_t=void*;
const int ESP_OK=0,HTTP_METHOD_POST=1;
struct esp_http_client_config_t {const char* url;const char* cert_pem;int method,timeout_ms,buffer_size_tx;bool disable_auto_redirect,skip_cert_common_name_check;};
void* esp_http_client_init(const esp_http_client_config_t*);
int esp_http_client_close(void*);int esp_http_client_cleanup(void*);
int esp_http_client_set_timeout_ms(void*,int);int esp_http_client_set_header(void*,const char*,const char*);
int esp_http_client_open(void*,int);int esp_http_client_write(void*,const char*,int);
int64_t esp_http_client_fetch_headers(void*);int esp_http_client_get_status_code(void*);
bool esp_http_client_is_complete_data_received(void*);int esp_http_client_read(void*,char*,int);
