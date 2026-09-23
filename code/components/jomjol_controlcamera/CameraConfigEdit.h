#pragma once
#include <string>
#include "StreamPreview.h"

namespace CameraConfigEdit {
inline std::string trim(const std::string& text) {
    const size_t a = text.find_first_not_of(" \t\r");
    if (a == std::string::npos) return "";
    return text.substr(a, text.find_last_not_of(" \t\r")-a+1);
}
inline std::string upper(std::string text) {
    for (char& ch : text) if (ch >= 'a' && ch <= 'z') ch -= 'a'-'A';
    return text;
}
// Edit only the numeric token; preserve all unrelated bytes and comments.
// Ambiguous/malformed configuration is refused, never normalized silently.
inline bool intensity(const std::string& input, int percent, std::string& output) {
    if (percent < 0 || percent > 100 || input.find('\0') != std::string::npos) return false;
    bool inCamera = false;
    size_t sections = 0, matches = 0, valueStart = 0, valueLength = 0;
    for (size_t start = 0; start < input.size();) {
        size_t end = input.find('\n', start);
        if (end == std::string::npos) end = input.size();
        const std::string line = input.substr(start, end-start);
        const std::string clean = trim(line);
        if ((!clean.empty() && clean[0] == '[') || clean.compare(0, 2, ";[") == 0) {
            inCamera = clean == "[TakeImage]";
            if (inCamera) ++sections;
        } else if (inCamera && !clean.empty() && clean[0] != ';' && clean[0] != '#') {
            const size_t equal = line.find('=');
            if (equal != std::string::npos && upper(trim(line.substr(0, equal))) == "LEDINTENSITY") {
                const size_t a = line.find_first_not_of(" \t", equal+1);
                if (a == std::string::npos) return false;
                size_t b = a;
                while (b < line.size() && line[b] >= '0' && line[b] <= '9') ++b;
                int oldValue;
                const std::string suffix = trim(line.substr(b));
                if (!StreamPreview::parse(line.substr(a, b-a).c_str(), oldValue) ||
                    (!suffix.empty() && suffix[0] != ';' && suffix[0] != '#')) return false;
                ++matches; valueStart = start+a; valueLength = b-a;
            }
        }
        start = end == input.size() ? end : end+1;
    }
    if (sections != 1 || matches != 1) return false;
    output = input;
    output.replace(valueStart, valueLength, std::to_string(percent));
    return true;
}
}
