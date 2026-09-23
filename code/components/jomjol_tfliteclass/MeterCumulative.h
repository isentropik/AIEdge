#pragma once
#include "MeterAccounting.h"

namespace meter {
struct CumulativeResult {
    bool available=false, current=false;
    int64_t anchorUs=0, throughUs=0;
    double minimumFt3=0, maximumFt3=0;
    double estimatedFt3=std::numeric_limits<double>::quiet_NaN();
    Status status=Status::Invalid;
};

// Consumption since a fixed same-boot anchor, never a sum of positive noisy
// deltas. Every new endpoint is compared with that anchor, so stationary jitter
// cannot ratchet consumption upward once per sample. Bounds are conditional on
// the caller's error assumptions; this is not a verified lifetime meter total.
class Cumulative {
    Frame anchor{};
    CumulativeResult result;
public:
    const CumulativeResult& current() const {return result;}
    bool anchorFrame(Frame& out) const {if(!result.available)return false;out=anchor;return true;}
    void stale(){result.current=false;result.estimatedFt3=std::numeric_limits<double>::quiet_NaN();}
    void reset(const Frame& frame) {
        anchor=frame;result=CumulativeResult{};
        result.available=true;result.current=true;
        result.anchorUs=result.throughUs=frame.captureUs;
        result.status=Status::WithinNoise;
    }
    bool observe(const Frame& frame,const Bounds& bounds) {
        if(!result.available || frame.clockId!=anchor.clockId || frame.captureUs<=result.throughUs)
            return false;
        const Interval whole=resolve(anchor,frame,bounds);
        if(whole.status==Status::Invalid || whole.status==Status::Review ||
           !std::isfinite(whole.minimumFt3) || !std::isfinite(whole.maximumFt3))return false;
        // Physical consumption cannot fall below a previously established lower
        // bound. Do not silently clamp a contradictory upper bound into agreement.
        const double lower=std::max(result.minimumFt3,whole.minimumFt3);
        if(whole.maximumFt3<lower)return false;
        result.current=true;result.throughUs=frame.captureUs;
        result.minimumFt3=lower;result.maximumFt3=whole.maximumFt3;
        result.estimatedFt3=whole.estimatedFt3;result.status=whole.status;
        if(std::isfinite(result.estimatedFt3) && result.estimatedFt3<lower) {
            result.estimatedFt3=std::numeric_limits<double>::quiet_NaN();
            result.status=Status::BoundedOnly;
        }
        return true;
    }
};
}
