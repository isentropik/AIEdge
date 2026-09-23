#pragma once
#include "ConfigJournal.h"
#include <atomic>
#include <cerrno>
#include <cstdio>
#ifdef _WIN32
#include <io.h>
#else
#include <unistd.h>
#endif

namespace ConfigStorage {
inline std::atomic<bool>& safe() { static std::atomic<bool> value{true}; return value; }
class Files : public ConfigJournal::Storage {
public:
    ConfigJournal::Read read(const std::string& path, std::string& bytes) override {
        FILE* file = fopen(path.c_str(), "rb");
        if (!file) return errno == ENOENT ? ConfigJournal::Read::Missing : ConfigJournal::Read::Error;
        bool ok = fseek(file, 0, SEEK_END) == 0;
        long length = ok ? ftell(file) : -1;
        ok = ok && length >= 0 && size_t(length) <= 2*ConfigJournal::limit+20;
        std::string result;
        if (ok) {
            ok = fseek(file, 0, SEEK_SET) == 0;
            result.resize(length);
            if (ok && length) ok = fread(&result[0], 1, length, file) == size_t(length);
            ok = ok && !ferror(file);
        }
        if (fclose(file) != 0) ok = false;
        if (!ok) return ConfigJournal::Read::Error;
        bytes.swap(result);
        return ConfigJournal::Read::Ok;
    }
    bool writeSync(const std::string& path, const std::string& bytes) override {
        if (bytes.size() > 2*ConfigJournal::limit+20) return false;
        FILE* file = fopen(path.c_str(), "wb");
        if (!file) return false;
        bool ok = fwrite(bytes.data(), 1, bytes.size(), file) == bytes.size();
        if (fflush(file) != 0) ok = false;
#ifdef _WIN32
        if (_commit(_fileno(file)) != 0) ok = false;
#else
        if (fsync(fileno(file)) != 0) ok = false;
#endif
        if (fclose(file) != 0) ok = false;
        return ok;
    }
    bool remove(const std::string& path) override { return std::remove(path.c_str()) == 0; }
};
}
