#pragma once
#include <cstdio>
#include <string>

// Do not depend on the optional ESP-IDF error-name lookup table.
inline std::string cameraInitReport(bool attempted, int error) {
    if (!attempted) return "Not attempted";
    if (error == 0) return "Success";
    char text[48];
    std::snprintf(text, sizeof(text), "Failed (0x%X)", static_cast<unsigned>(error));
    return text;
}
