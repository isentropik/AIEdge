#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace AIEdgeRecovery {
// Same versioned NVS format written by bootstrap/SavedWifi.h. Never modify it here.
inline bool decodeWifi(const uint8_t* data, size_t size, char (&ssid)[32], char (&password)[64]) {
    std::memset(ssid, 0, sizeof ssid);
    std::memset(password, 0, sizeof password);
    if (!data || size < 3 || data[0] != 1 || data[1] == 0 || data[1] > 31 ||
        data[2] > 63 || (data[2] && data[2] < 8) || size != size_t(3 + data[1] + data[2])) return false;
    for (size_t i = 3; i < size; ++i)
        if (!data[i] || data[i] == '\r' || data[i] == '\n' || data[i] == '"') return false;
    std::memcpy(ssid, data + 3, data[1]);
    std::memcpy(password, data + 3 + data[1], data[2]);
    return true;
}
}
