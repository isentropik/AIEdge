#pragma once
#include <string>

// ZIP names are relative slash-separated paths, never host/device paths.
inline bool safeArchivePath(const std::string& path) {
    if(path.empty() || path.front()=='/' || path.find('\\')!=std::string::npos ||
       path.find(':')!=std::string::npos || path.find('\0')!=std::string::npos)return false;
    size_t start=0;
    while(start<path.size()) {
        const size_t end=path.find('/',start);
        const auto part=path.substr(start,end==std::string::npos ? end : end-start);
        if(part.empty() || part=="." || part=="..")return false;
        for(unsigned char c:part)if(c<32 || c==127)return false;
        if(end==std::string::npos)return true;
        start=end+1;
    }
    return true; // An explicit directory entry may end in '/'.
}
