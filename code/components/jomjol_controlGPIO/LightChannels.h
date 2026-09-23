#pragma once
#include <cstdint>
#include <string>

namespace illumination {
struct Channels { uint8_t r,g,b,w; };
constexpr int maximumDuty = 8191;
inline bool parseChannel(const std::string& text,uint8_t& output) {
    if (text.empty()) return false;
    unsigned value=0;
    for (char c:text) {
        if (c<'0' || c>'9') return false;
        value=value*10+unsigned(c-'0');
        if (value>255) return false;
    }
    output=static_cast<uint8_t>(value);
    return true;
}
inline int clampDuty(int duty) { return duty<0 ? 0 : duty>maximumDuty ? maximumDuty : duty; }
inline uint8_t scaleChannel(uint8_t channel,int duty) {
    return static_cast<uint8_t>((uint32_t(channel)*clampDuty(duty)+maximumDuty/2)/maximumDuty);
}
inline Channels scale(Channels color,int duty,bool enabled) {
    if (!enabled) return {0,0,0,0};
    return {scaleChannel(color.r,duty),scaleChannel(color.g,duty),
            scaleChannel(color.b,duty),scaleChannel(color.w,duty)};
}
}
