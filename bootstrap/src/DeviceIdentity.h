#pragma once
#include <cstdint>
#include <cstdio>
#include <string>
namespace AIEdgeIdentity {
inline std::string hostname(const uint8_t mac[6]) {
 char result[20];
 snprintf(result,sizeof result,"aiedge-%02x%02x%02x",mac[3],mac[4],mac[5]);
 return result;
}
constexpr int maxReleaseUrlBytes=4096;
// ESP-IDF constructs the entire request line in its TX buffer, including query.
constexpr int httpRequestBufferBytes=maxReleaseUrlBytes+32;
}
