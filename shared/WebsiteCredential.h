#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace AIEdgeAuth {
// One versioned blob, independent of the SD card. The checksum detects damaged
// records; it is not a signature or protection against physical flash access.
constexpr size_t credentialBytes = 88;
constexpr unsigned passwordIterations = 20000;
enum class State { Uninitialized, NeedsSetup, Ready, StorageError };
enum class ReadResult { Missing, Present, Error };
struct Backend {
    virtual ~Backend() = default;
    virtual ReadResult read(uint8_t* record, size_t size) = 0;
    virtual bool write(const uint8_t* record, size_t size) = 0;
    virtual bool eraseCredential() = 0;
    virtual bool random(uint8_t* bytes, size_t size) = 0;
    virtual bool derive(const uint8_t* password, size_t size, const uint8_t* salt, uint8_t* result) = 0;
    virtual bool digest(const uint8_t* bytes, size_t size, uint8_t* result) = 0;
};
inline void wipe(void* data, size_t size) {
    volatile uint8_t* bytes = static_cast<volatile uint8_t*>(data);
    while (size--) *bytes++ = 0;
}
inline bool equal(const uint8_t* left, const uint8_t* right, size_t size) {
    unsigned difference = 0;
    for (size_t i = 0; i < size; ++i) difference |= left[i] ^ right[i];
    return difference == 0;
}
class Credential {
    Backend& backend;
    uint8_t active[credentialBytes] = {};
    State current = State::Uninitialized;
    bool valid(const uint8_t* record) {
        constexpr uint8_t prefix[] = {'A','I','E','A',1,0,0,0};
        uint8_t checksum[32] = {};
        const bool ok = equal(record, prefix, sizeof prefix) &&
            backend.digest(record, 56, checksum) && equal(checksum, record + 56, 32);
        wipe(checksum, sizeof checksum);
        return ok;
    }
public:
    explicit Credential(Backend& storage) : backend(storage) {}
    ~Credential() { wipe(active, sizeof active); }
    Credential(const Credential&) = delete;
    Credential& operator=(const Credential&) = delete;
    State state() const { return current; }
    State load() {
        wipe(active, sizeof active);
        const auto result = backend.read(active, sizeof active);
        current = result == ReadResult::Missing ? State::NeedsSetup :
            result == ReadResult::Present && valid(active) ? State::Ready : State::StorageError;
        if (current != State::Ready) wipe(active, sizeof active);
        return current;
    }
    // Only an explicitly confirmed local recovery command may invoke this.
    bool resetForLocalRecovery() {
        current=State::StorageError;wipe(active,sizeof active);
        uint8_t record[credentialBytes]={};
        const bool ok=backend.eraseCredential()&&backend.read(record,sizeof record)==ReadResult::Missing;
        wipe(record,sizeof record);
        if(ok)current=State::NeedsSetup;
        return ok;
    }
    bool verify(const uint8_t* password, size_t size) {
        if (current != State::Ready || !password || !size || size > 128) return false;
        uint8_t candidate[32] = {};
        const bool ok = backend.derive(password, size, active + 8, candidate) && equal(candidate, active + 24, 32);
        wipe(candidate, sizeof candidate);
        return ok;
    }
    // Caller must authorize first-time setup or an authenticated password change.
    // This class is not an HTTP authorization gate and provides no network reset.
    bool save(const uint8_t* password, size_t size) {
        if ((current != State::NeedsSetup && current != State::Ready) || !password || size < 12 || size > 128)
            return false;
        for (size_t i=0; i<size; ++i) if (password[i] < 0x20 || password[i] == 0x7f) return false;
        uint8_t candidate[credentialBytes] = {'A','I','E','A',1,0,0,0};
        bool ok = backend.random(candidate + 8, 16) &&
            backend.derive(password, size, candidate + 8, candidate + 24) &&
            backend.digest(candidate, 56, candidate + 56);
        if (ok) {
            // Any uncertain write locks the current session until a fresh load.
            current = State::StorageError;
            wipe(active, sizeof active);
            ok = backend.write(candidate, sizeof candidate) &&
                backend.read(active, sizeof active) == ReadResult::Present &&
                equal(candidate, active, sizeof active) && valid(active);
            if (ok) current = State::Ready;
            else wipe(active, sizeof active);
        }
        wipe(candidate, sizeof candidate);
        return ok;
    }
};
}
