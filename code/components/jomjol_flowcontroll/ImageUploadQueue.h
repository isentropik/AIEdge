#pragma once
#include <array>
#include <cstdint>
#include <limits>
#include <string>

// Single-owner upload worker state. Payloads live in a verified disk spool, not
// this queue. No entry may be deleted from disk until acknowledged() is true.
// Restore pending entries from the spool after reboot; never restore timers.
namespace ImageArchive {
inline bool validHash(const std::string& value) {
    if (value.size() != 64) return false;
    for (char c : value) if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
    return true;
}
struct Identity {
    std::string capture, image, record;
    uint32_t bytes = 0;
    bool valid() const {
        return validHash(capture) && validHash(image) && validHash(record) &&
               bytes > 0 && bytes <= 2 * 1024 * 1024;
    }
    bool operator==(const Identity& other) const {
        return capture == other.capture && image == other.image &&
               record == other.record && bytes == other.bytes;
    }
};
enum class State { Empty, Pending, Uploading, Acknowledged, Blocked };
enum class Admission { Added, Duplicate, Conflict, Full, Invalid };
struct Receipt {
    int version = 0;
    std::string capture, image, record, reviewStatus;
    bool verifiedReadback = false, trainingEligible = true;
    bool matches(const Identity& id) const {
        return version == 1 && verifiedReadback && !trainingEligible &&
               reviewStatus == "unreviewed" && capture == id.capture &&
               image == id.image && record == id.record;
    }
};
struct Ticket {
    size_t slot = 0;
    uint64_t serial = 0;
    Identity identity;
};
struct Entry {
    State state = State::Empty;
    Identity identity;
    uint64_t serial = 0, dueMs = 0;
    uint32_t failures = 0;
};
class UploadQueue {
public:
    static constexpr size_t Capacity = 8;
    static constexpr uint32_t ByteLimit = 8 * 1024 * 1024;
    Admission add(const Identity& identity) {
        if (!identity.valid()) return Admission::Invalid;
        for (const auto& e : entries) if (e.state != State::Empty && e.identity.capture == identity.capture)
            return e.identity == identity ? Admission::Duplicate : Admission::Conflict;
        if (identity.bytes > ByteLimit - bytesUsed) return Admission::Full;
        for (auto& e : entries) if (e.state == State::Empty) {
            e = Entry{}; e.identity = identity; e.state = State::Pending;
            bytesUsed += identity.bytes;
            return Admission::Added;
        }
        return Admission::Full;
    }
    bool begin(uint64_t nowMs, Ticket& ticket) {
        for (const auto& e : entries) if (e.state == State::Uploading) return false;
        if (serial == std::numeric_limits<uint64_t>::max()) return false;
        for (size_t n = 0; n < Capacity; ++n) {
            const size_t i = (cursor + n) % Capacity;
            auto& e = entries[i];
            if (e.state != State::Pending || e.dueMs > nowMs) continue;
            e.state = State::Uploading; e.serial = ++serial;
            ticket.slot = i; ticket.serial = e.serial; ticket.identity = e.identity;
            cursor = (i + 1) % Capacity;
            return true;
        }
        return false;
    }
    bool finish(const Ticket& ticket, uint64_t nowMs, int httpStatus, const Receipt& receipt) {
        if (ticket.slot >= Capacity) return false;
        auto& e = entries[ticket.slot];
        if (e.state != State::Uploading || e.serial != ticket.serial || !(e.identity == ticket.identity)) return false;
        if ((httpStatus == 200 || httpStatus == 201) && receipt.matches(e.identity)) {
            e.state = State::Acknowledged;
        } else if (httpStatus == 400 || httpStatus == 401 || httpStatus == 403 || httpStatus == 404 ||
                   httpStatus == 409 || httpStatus == 413 || (httpStatus >= 200 && httpStatus < 300)) {
            // An invalid success receipt is not permission to discard the image.
            // Keep for explicit operator/configuration repair, without hammering.
            e.state = State::Blocked;
        } else {
            if (e.failures < 16) ++e.failures;
            uint64_t delay = 5000ULL << (e.failures - 1);
            if (delay > 300000) delay = 300000;
            e.dueMs = nowMs > std::numeric_limits<uint64_t>::max() - delay ?
                      std::numeric_limits<uint64_t>::max() : nowMs + delay;
            e.state = State::Pending;
        }
        return true;
    }
    bool acknowledged(const Ticket& ticket) const {
        return ticket.slot < Capacity && entries[ticket.slot].state == State::Acknowledged &&
               entries[ticket.slot].serial == ticket.serial && entries[ticket.slot].identity == ticket.identity;
    }
    // Call only after acknowledged payload/record deletion succeeds. If deletion
    // fails, keep the slot; a reboot reuploads the same immutable identity safely.
    bool release(const Ticket& ticket) {
        if (!acknowledged(ticket)) return false;
        bytesUsed -= entries[ticket.slot].identity.bytes;
        entries[ticket.slot] = Entry{};
        return true;
    }
    const std::array<Entry, Capacity>& status() const { return entries; }
    uint32_t queuedBytes() const { return bytesUsed; }
private:
    std::array<Entry, Capacity> entries{};
    uint32_t bytesUsed = 0;
    uint64_t serial = 0;
    size_t cursor = 0;
};
} // namespace ImageArchive
