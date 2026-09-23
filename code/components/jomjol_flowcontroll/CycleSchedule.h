#pragma once
#include <cstdint>
#include <limits>

namespace CycleSchedule {
struct Next { bool valid=false; int64_t atUs=0; uint64_t missed=0; };
// Preserve cadence; discard missed slots instead of queueing catch-up work.
inline Next after(int64_t slotUs, int64_t nowUs, int64_t periodUs) {
    Next result;
    const int64_t maximum=std::numeric_limits<int64_t>::max();
    if (slotUs < 0 || nowUs < slotUs || periodUs <= 0 || slotUs > maximum-periodUs)
        return result;
    int64_t next=slotUs+periodUs;
    if (nowUs > next) {
        const int64_t late=nowUs-next;
        const int64_t skipped=late/periodUs+(late%periodUs != 0);
        if (skipped > (maximum-next)/periodUs) return result;
        result.missed=static_cast<uint64_t>(skipped);
        next+=skipped*periodUs;
    }
    result.valid=true;result.atUs=next;
    return result;
}
}
