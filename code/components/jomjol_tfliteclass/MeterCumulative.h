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
// deltas. Every new endpoint is compared with that anchor; uniquely established
// discrete turns are retained from intervening frames, so stationary jitter
// cannot ratchet consumption upward once per sample. Bounds are conditional on
// the caller's error assumptions; this is not a verified lifetime meter total.
class Cumulative {
    Frame anchor{};
    Frame previous{};
    bool trackedTurns=false;
    int64_t turnOffset=0;
    CumulativeResult result;
public:
    const CumulativeResult& current() const {return result;}
    bool anchorFrame(Frame& out) const {if(!result.available)return false;out=anchor;return true;}
    void stale(){result.current=false;result.estimatedFt3=std::numeric_limits<double>::quiet_NaN();}
    void reset(const Frame& frame) {
        anchor=previous=frame;trackedTurns=true;turnOffset=0;result=CumulativeResult{};
        result.available=true;result.current=true;
        result.anchorUs=result.throughUs=frame.captureUs;
        result.status=Status::WithinNoise;
    }
    bool observe(const Frame& frame,const Bounds& bounds) {
        if(!result.available || frame.clockId!=anchor.clockId || frame.captureUs<=result.throughUs)
            return false;
        Interval whole=resolve(anchor,frame,bounds);
        if(whole.status==Status::Invalid || whole.status==Status::Review ||
           !std::isfinite(whole.minimumFt3) || !std::isfinite(whole.maximumFt3))return false;
        // Propagate only discrete, uniquely established turn offsets. Never sum
        // positive noisy volumes: the phase still comes from the fixed anchor.
        const Interval step=resolve(previous,frame,bounds);
        bool nextTracked=trackedTurns && step.candidates==1 &&
            step.status!=Status::Invalid && step.status!=Status::Review;
        int64_t nextOffset=turnOffset;
        if(nextTracked) {
            const int64_t delta=step.firstTurnOffset;
            if((delta>0 && turnOffset>std::numeric_limits<int64_t>::max()-delta) ||
               (delta<0 && turnOffset<std::numeric_limits<int64_t>::min()-delta))return false;
            nextOffset+=delta;
            if(nextOffset<whole.firstTurnOffset || nextOffset>whole.lastTurnOffset)return false;
            const double estimate=whole.rawPhaseDelta+secondaryRevolutionFt3*nextOffset;
            const double error=bounds.secondaryDial+numericalSlackFt3;
            const double lo=std::max(whole.minimumFt3,estimate-error);
            const double hi=std::min(whole.maximumFt3,estimate+error);
            if(lo>hi)return false;
            whole.minimumFt3=lo;whole.maximumFt3=hi;
            whole.estimatedFt3=std::numeric_limits<double>::quiet_NaN();
            if(estimate<=error+1e-9)whole.status=Status::WithinNoise;
            else if(estimate<lo-1e-9 || estimate>hi+1e-9)whole.status=Status::BoundedOnly;
            else {whole.status=Status::Estimated;whole.estimatedFt3=estimate;}
        } else if(whole.candidates==1) {
            // The main register may resolve a previously ambiguous gap later.
            nextTracked=true;nextOffset=whole.firstTurnOffset;
        }
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
        previous=frame;trackedTurns=nextTracked;turnOffset=nextOffset;
        return true;
    }
};
}
