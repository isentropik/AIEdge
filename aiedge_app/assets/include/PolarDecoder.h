#pragma once
#include <cstddef>
#include <cstdint>
#include <cmath>

// Frozen polar model output: 360 int8 probabilities, scale 1/256, zero -128.
// The scale cancels in the weighted centroid. Never interpret bytes as floats.
namespace polar {
inline bool decode(const int8_t* values, size_t count, bool ccw, float& result) {
    if (!values || count != 360) return false;
    int peak = 0;
    for (int i = 1; i < 360; ++i)
        if (values[i] > values[peak]) peak = i;
    int mass = 0, moment = 0;
    for (int offset = -10; offset <= 10; ++offset) {
        const int bin = (peak + offset + 360) % 360;
        const int weight = static_cast<int>(values[bin]) + 128;
        mass += weight;
        moment += offset * weight;
    }
    if (mass == 0) return false;
    double bin = std::fmod(peak + static_cast<double>(moment) / mass + 360.0, 360.0);
    double value = bin / 36.0;
    if (ccw) value = std::fmod(10.0 - value, 10.0);
    result = static_cast<float>(value);
    // Float rounding must not manufacture a value outside [0,10).
    if (result >= 10.0f) result = 0.0f;
    return true;
}
}
