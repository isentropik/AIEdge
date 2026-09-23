#include "basic_auth.h"
#include "read_wlanini.h"
#include <esp_tls_crypto.h>
#include <esp_log.h>
#include <cstring>
#include <string>
#include <vector>

namespace {
constexpr const char* TAG = "HTTPAUTH";
// Owned snapshot: editing wlan_config must not invalidate active credentials.
std::string expectedAuthorization;
bool authenticationRequired = false;

esp_err_t deny(httpd_req_t* req) {
    httpd_resp_set_status(req, "401 Unauthorized");
    httpd_resp_set_type(req, "text/plain; charset=utf-8");
    httpd_resp_set_hdr(req, "Cache-Control", "no-store");
    httpd_resp_set_hdr(req, "WWW-Authenticate", "Basic realm=\"AIEdge\", charset=\"UTF-8\"");
    constexpr char message[] = "Sign in to AIEdge.";
    return httpd_resp_send(req, message, sizeof(message) - 1);
}
}

bool basic_auth_configured() { return !expectedAuthorization.empty(); }

void init_basic_auth() {
    expectedAuthorization.clear();
    authenticationRequired = !wlan_config.http_username.empty() || !wlan_config.http_password.empty();
    if (!authenticationRequired) return;
    if (wlan_config.http_username.empty() || wlan_config.http_password.empty() ||
        wlan_config.http_username.find(':') != std::string::npos) {
        ESP_LOGE(TAG, "Incomplete or invalid website credentials; access denied");
        return;
    }
    const std::string value = wlan_config.http_username + ":" + wlan_config.http_password;
    size_t capacity = 0;
    esp_crypto_base64_encode(nullptr, 0, &capacity,
        reinterpret_cast<const unsigned char*>(value.data()), value.size());
    if (!capacity) return;
    std::vector<unsigned char> encoded(capacity);
    size_t written = 0;
    if (esp_crypto_base64_encode(encoded.data(), encoded.size(), &written,
            reinterpret_cast<const unsigned char*>(value.data()), value.size()) != 0 ||
        !written || written >= encoded.size()) {
        ESP_LOGE(TAG, "Website credential encoding failed; access denied");
        return;
    }
    expectedAuthorization = "Basic " + std::string(reinterpret_cast<const char*>(encoded.data()), written);
}

esp_err_t basic_auth_request_filter(httpd_req_t* req, esp_err_t original_handler(httpd_req_t*)) {
    // Mandatory first-time setup is not wired in yet. A partially configured password
    // must never silently revert to unrestricted access.
    if (!authenticationRequired) return original_handler(req);
    const size_t length = httpd_req_get_hdr_value_len(req, "Authorization");
    if (expectedAuthorization.empty() || length != expectedAuthorization.size()) return deny(req);
    std::vector<char> supplied(length + 1, 0);
    if (httpd_req_get_hdr_value_str(req, "Authorization", supplied.data(), supplied.size()) != ESP_OK)
        return deny(req);
    // Compare every byte, including any embedded NUL; no prefix acceptance.
    unsigned difference = 0;
    for (size_t i = 0; i < length; ++i)
        difference |= static_cast<unsigned char>(supplied[i]) ^ static_cast<unsigned char>(expectedAuthorization[i]);
    return difference ? deny(req) : original_handler(req);
}
