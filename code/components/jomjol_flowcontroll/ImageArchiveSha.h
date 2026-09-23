#pragma once
#include "mbedtls/sha256.h"
#include <string>

namespace ImageArchive {
class Sha256 {
    mbedtls_sha256_context context;
    bool healthy=false, finished=false;
public:
    Sha256() {mbedtls_sha256_init(&context);healthy=mbedtls_sha256_starts(&context,0)==0;}
    ~Sha256() {mbedtls_sha256_free(&context);}
    Sha256(const Sha256&)=delete;
    Sha256& operator=(const Sha256&)=delete;
    bool update(const unsigned char* bytes,size_t length) {
        if(finished || !healthy) return false;
        if(!bytes && length) {healthy=false;return false;}
        healthy=mbedtls_sha256_update(&context,bytes,length)==0;
        return healthy;
    }
    std::string finish() {
        if(finished || !healthy) return "";
        finished=true;
        unsigned char bytes[32];
        if(mbedtls_sha256_finish(&context,bytes)!=0) {healthy=false;return "";}
        const char* hex="0123456789abcdef";
        std::string result;result.reserve(64);
        for(auto b:bytes) {result.push_back(hex[b>>4]);result.push_back(hex[b&15]);}
        return result;
    }
};
}
