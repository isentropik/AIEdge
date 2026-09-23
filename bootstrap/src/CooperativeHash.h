#pragma once
#include <cstddef>
namespace AIEdgeSetup {
// Keep the existing digest implementation, yielding between bounded chunks.
template<class Hash, void (*Yield)()> class CooperativeHash : public Hash {
    size_t sinceYield = 0;
public:
    bool update(const unsigned char* data, size_t size) {
        const bool ok = Hash::update(data, size);
        sinceYield += size;
        if (sinceYield >= 32768) { sinceYield = 0; Yield(); }
        return ok;
    }
};
}
