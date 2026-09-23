#pragma once

#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "esp_http_server.h"

inline esp_err_t cameraBusyResponse(httpd_req_t* request) {
    esp_err_t result = httpd_resp_set_status(request, "503 Service Unavailable");
    if (result != ESP_OK) return result;
    result = httpd_resp_set_hdr(request, "Retry-After", "1");
    if (result != ESP_OK) return result;
    return httpd_resp_send(request, "Camera busy; retry shortly", HTTPD_RESP_USE_STRLEN);
}

// One lock covers sensor settings, frame acquisition and capture illumination.
// Recursive because endpoint transactions call lower-level camera methods.
SemaphoreHandle_t cameraAccessMutex();

class CameraAccess {
    SemaphoreHandle_t mutex;
    bool acquired;
public:
    explicit CameraAccess(TickType_t wait = 0)
        : mutex(cameraAccessMutex()),
          acquired(mutex && xSemaphoreTakeRecursive(mutex, wait) == pdTRUE) {}
    ~CameraAccess() { if (acquired) xSemaphoreGiveRecursive(mutex); }
    explicit operator bool() const { return acquired; }
    CameraAccess(const CameraAccess&) = delete;
    CameraAccess& operator=(const CameraAccess&) = delete;
};
