#pragma once
#include <cstdio>
#include <algorithm>
inline bool seekCompleteDataTail(FILE* file, long limit) {
    if (!file || limit <= 0 || std::fseek(file, 0, SEEK_END)) return false;
    const long size = std::ftell(file);
    if (size < 0) return false;
    const long start = std::max(0L, size-limit);
    if (std::fseek(file, start ? start-1 : 0, SEEK_SET)) return false;
    if (start) {
        int ch;
        while ((ch=std::fgetc(file)) != '\n' && ch != EOF) {}
    }
    return !std::ferror(file);
}
