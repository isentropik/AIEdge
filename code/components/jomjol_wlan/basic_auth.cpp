#include "basic_auth.h"
#include "WebsiteCredentialStore.h"

void init_basic_auth() { AIEdgeAuth::deviceWebsiteHttp().initialize(); }
bool basic_auth_configured() { return AIEdgeAuth::deviceWebsiteHttp().configured(); }
esp_err_t basic_auth_request_filter(httpd_req_t* req, esp_err_t handler(httpd_req_t*)) {
    return AIEdgeAuth::deviceWebsiteHttp().handle(req,handler);
}
namespace {
esp_err_t unused(httpd_req_t*) { return ESP_FAIL; }
esp_err_t setup(httpd_req_t* req) { return basic_auth_request_filter(req,unused); }
}
esp_err_t register_website_auth(httpd_handle_t server) {
    httpd_uri_t route={};route.uri="/auth/setup";route.method=HTTP_POST;route.handler=setup;
    auto result=httpd_register_uri_handler(server,&route);if(result!=ESP_OK)return result;
    route.method=HTTP_GET;return httpd_register_uri_handler(server,&route);
}
