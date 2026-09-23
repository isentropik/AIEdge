#pragma once
#include <cstdint>
#include <string>

namespace ConfigJournal {
enum class Read { Ok, Missing, Error };
enum class Result { Ok, Conflict, IoError, InvalidJournal, CleanupPending };
struct Storage {
    virtual Read read(const std::string& path, std::string& bytes) = 0;
    virtual bool writeSync(const std::string& path, const std::string& bytes) = 0;
    virtual bool remove(const std::string& path) = 0;
    virtual ~Storage() {}
};
constexpr size_t limit = 64 * 1024;
inline uint32_t crc(const std::string& bytes) {
    uint32_t value = 0xffffffff;
    for (unsigned char ch : bytes) {
        value ^= ch;
        for (int bit = 0; bit < 8; ++bit)
            value = (value >> 1) ^ ((value & 1) ? 0xedb88320 : 0);
    }
    return ~value;
}
inline void append32(std::string& bytes, uint32_t value) {
    for (int i = 0; i < 4; ++i) bytes.push_back(static_cast<char>(value >> (8*i)));
}
inline uint32_t get32(const std::string& bytes, size_t pos) {
    uint32_t result = 0;
    for (int i = 0; i < 4; ++i) result |= uint32_t(static_cast<unsigned char>(bytes[pos+i])) << (8*i);
    return result;
}
inline std::string encode(const std::string& before, const std::string& after) {
    std::string result = "CFGJ0001";
    append32(result, before.size()); append32(result, after.size());
    result += before; result += after;
    append32(result, crc(result));
    return result;
}
inline bool decode(const std::string& record, std::string& before, std::string& after) {
    if (record.size() < 20 || record.compare(0, 8, "CFGJ0001")) return false;
    const size_t a = get32(record, 8), b = get32(record, 12);
    if (!a || !b || a > limit || b > limit || record.size() != 20+a+b) return false;
    if (crc(record.substr(0, record.size()-4)) != get32(record, record.size()-4)) return false;
    before = record.substr(16, a); after = record.substr(16+a, b);
    return true;
}
inline bool verifiedWrite(Storage& storage, const std::string& path, const std::string& bytes) {
    if (!storage.writeSync(path, bytes)) return false;
    std::string readback;
    return storage.read(path, readback) == Read::Ok && readback == bytes;
}
// Called before parsing config, and before another transaction. A corrupt journal
// is never guessed away; retain all evidence and refuse initialization.
inline Result recover(Storage& storage, const std::string& path) {
    const std::string journal = path + ".journal";
    std::string record, before, after, current;
    const Read status = storage.read(journal, record);
    if (status == Read::Missing) return Result::Ok;
    if (status != Read::Ok) return Result::IoError;
    if (!decode(record, before, after)) return Result::InvalidJournal;
    const Read present = storage.read(path, current);
    if (present == Read::Error) return Result::IoError;
    if (present != Read::Ok || (current != before && current != after)) {
        if (!verifiedWrite(storage, path, before)) return Result::IoError;
    }
    return storage.remove(journal) ? Result::Ok : Result::CleanupPending;
}
inline Result commit(Storage& storage, const std::string& path,
                     const std::string& before, const std::string& after) {
    if (before.empty() || after.empty() || before.size()>limit || after.size()>limit)
        return Result::Conflict;
    Result recovered = recover(storage, path);
    // CleanupPending here belongs to an earlier transaction, not this request.
    if (recovered == Result::CleanupPending) return Result::IoError;
    if (recovered != Result::Ok) return recovered;
    std::string current;
    if (storage.read(path, current) != Read::Ok) return Result::IoError;
    if (current != before) return Result::Conflict;
    if (before == after) return Result::Ok;
    const std::string journal = path + ".journal";
    if (!verifiedWrite(storage, journal, encode(before, after))) return Result::IoError;
    if (!verifiedWrite(storage, path, after)) {
        // Retain journal unless restoration itself is verified.
        if (verifiedWrite(storage, path, before)) storage.remove(journal);
        return Result::IoError;
    }
    return storage.remove(journal) ? Result::Ok : Result::CleanupPending;
}
}
