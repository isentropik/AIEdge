#pragma once
#include "WebsiteCredential.h"
#include "nvs.h"
#include "esp_random.h"
#include "mbedtls/pkcs5.h"
#include "mbedtls/sha256.h"

namespace AIEdgeAuth {
class NvsBackend final : public Backend {
public:
    ReadResult read(uint8_t* record, size_t size) override {
        nvs_handle_t handle;
        const auto opened = nvs_open("aiedge_auth", NVS_READONLY, &handle);
        if (opened == ESP_ERR_NVS_NOT_FOUND) return ReadResult::Missing;
        if (opened != ESP_OK) return ReadResult::Error;
        size_t actual = size;
        const auto result = nvs_get_blob(handle, "credential", record, &actual);
        nvs_close(handle);
        if (result == ESP_ERR_NVS_NOT_FOUND) return ReadResult::Missing;
        return result == ESP_OK && actual == size ? ReadResult::Present : ReadResult::Error;
    }
    bool write(const uint8_t* record, size_t size) override {
        nvs_handle_t handle;
        if (nvs_open("aiedge_auth", NVS_READWRITE, &handle) != ESP_OK) return false;
        const bool ok = nvs_set_blob(handle, "credential", record, size) == ESP_OK && nvs_commit(handle) == ESP_OK;
        nvs_close(handle);
        return ok;
    }
    bool random(uint8_t* bytes, size_t size) override {
        // Provision only after Wi-Fi has started, when the hardware RNG has RF entropy.
        esp_fill_random(bytes, size);
        return true;
    }
    bool derive(const uint8_t* password, size_t size, const uint8_t* salt, uint8_t* result) override {
        return mbedtls_pkcs5_pbkdf2_hmac_ext(MBEDTLS_MD_SHA256, password, size, salt, 16,
                                           passwordIterations, 32, result) == 0;
    }
    bool digest(const uint8_t* bytes, size_t size, uint8_t* result) override {
        return mbedtls_sha256(bytes, size, result, 0) == 0;
    }
};
}
