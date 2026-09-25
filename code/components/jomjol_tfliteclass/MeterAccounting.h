#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>

// Physical conversions shared with needle_reader_v2/cumulative_check.py and
// meter_interval.py. Positions are already normalized into each dial's numbering.
// Never use output estimates as labels or alter raw positions to force agreement.
namespace meter {
constexpr double secondaryRevolutionFt3 = 5.0;
constexpr double lastMainRevolutionFt3 = 1000.0;
constexpr double registerRevolutionFt3 = 10000000.0;
constexpr double numericalSlackFt3 = 1e-7; // Roundoff only, not reading accuracy.
enum class Status { Invalid, Review, Ambiguous, WithinNoise, BoundedOnly, Estimated };
enum class Reason {
    InvalidBounds, CaptureTimeRequired, MainUnknown, MainInconsistent, SecondaryUnknown,
    RegisterRolloverOrReset, BackwardMain, MainRateContradiction, SecondaryMainContradiction,
    TurnCountUnresolved, SecondaryNoise, UncertaintyTailsOnly, UniqueUnderBounds, ClockDomainMismatch,
    CumulativeContradiction, AccountingUnavailable
};
struct Frame {
    double main[5];
    double secondary;
    int64_t captureUs;
    bool captureTimeValid;
    uint64_t clockId = 0; // Boot identity for driver uptime; never compare across boots.
};
struct Bounds {
    double mainDial = .1;
    double secondaryDial = .1;
    bool hasMaximumRate = false;
    double maximumRateFt3S = 0;
};
struct Interval {
    Status status = Status::Invalid;
    Reason reason = Reason::InvalidBounds;
    int64_t candidates = 0, firstTurnOffset = 0, lastTurnOffset = 0;
    double elapsedSeconds = 0;
    double rawMainDelta = std::numeric_limits<double>::quiet_NaN();
    double rawPhaseDelta = std::numeric_limits<double>::quiet_NaN();
    double minimumFt3 = std::numeric_limits<double>::quiet_NaN();
    double maximumFt3 = std::numeric_limits<double>::quiet_NaN();
    double estimatedFt3 = std::numeric_limits<double>::quiet_NaN();
    double averageFt3S = std::numeric_limits<double>::quiet_NaN();
};
inline bool validPosition(double value) {
    return std::isfinite(value) && value >= 0 && value < 10;
}
inline double circularDistance(double a,double b,double period) {
    double difference = std::fmod(a-b+period/2,period);
    if (difference < 0) difference += period;
    return std::abs(difference-period/2);
}
inline bool reconstruct(const double* values,double& total) {
    if (!values) return false;
    for (int i=0;i<5;++i) if (!validPosition(values[i])) return false;
    double reconstructed=values[4]*100;
    double revolution=10000;
    for (int i=3;i>=0;--i,revolution*=10) {
        const double step=revolution/10,expected=values[i]*step;
        double best=0,bestDistance=std::numeric_limits<double>::infinity();
        for (int k=0;k<10;++k) {
            const double candidate=k*step+reconstructed;
            const double distance=circularDistance(candidate,expected,revolution);
            if (distance<bestDistance) {best=candidate;bestDistance=distance;}
        }
        reconstructed=best;
    }
    total=reconstructed;
    return true;
}
inline bool consistent(const double* values,double tolerance) {
    if (!values || !std::isfinite(tolerance) || tolerance<0 || tolerance>=.5) return false;
    for (int i=0;i<5;++i) if (!validPosition(values[i])) return false;
    for (int i=0;i<4;++i) {
        double residual=std::numeric_limits<double>::infinity();
        for (int k=0;k<10;++k)
            residual=std::min(residual,circularDistance(k+values[i+1]/10,values[i],10));
        if (residual>tolerance+tolerance/10+1e-9) return false;
    }
    return true;
}
inline Interval resolve(const Frame& previous,const Frame& current,const Bounds& bounds) {
    Interval result;
    if (!std::isfinite(bounds.mainDial) || bounds.mainDial<0 || bounds.mainDial>=.5 ||
        !std::isfinite(bounds.secondaryDial) || bounds.secondaryDial<0 || bounds.secondaryDial>=.5 ||
        (bounds.hasMaximumRate && (!std::isfinite(bounds.maximumRateFt3S) || bounds.maximumRateFt3S<0)))
        return result;
    result.reason=Reason::CaptureTimeRequired;
    if (!previous.captureTimeValid || !current.captureTimeValid || previous.captureUs<0 ||
        current.captureUs<=previous.captureUs) return result;
    if (!previous.clockId || previous.clockId != current.clockId) {
        result.reason=Reason::ClockDomainMismatch;return result;
    }
    result.elapsedSeconds=static_cast<double>(current.captureUs-previous.captureUs)/1000000;
    double oldTotal,newTotal;
    result.reason=Reason::MainUnknown;
    if (!reconstruct(previous.main,oldTotal) || !reconstruct(current.main,newTotal)) return result;
    if (!consistent(previous.main,bounds.mainDial) || !consistent(current.main,bounds.mainDial)) {
        result.status=Status::Review;result.reason=Reason::MainInconsistent;return result;
    }
    result.reason=Reason::SecondaryUnknown;
    if (!validPosition(previous.secondary) || !validPosition(current.secondary)) return result;
    result.rawMainDelta=newTotal-oldTotal;
    result.rawPhaseDelta=(current.secondary-previous.secondary)*.5;
    const double mainError=2*bounds.mainDial*100+numericalSlackFt3;
    const double phaseError=bounds.secondaryDial+numericalSlackFt3;
    result.status=Status::Review;
    if (result.rawMainDelta<-registerRevolutionFt3/2) {
        result.reason=Reason::RegisterRolloverOrReset;return result;
    }
    if (result.rawMainDelta+mainError<-1e-9) {result.reason=Reason::BackwardMain;return result;}
    const double lower=std::max(0.0,result.rawMainDelta-mainError);
    double upper=result.rawMainDelta+mainError;
    if (bounds.hasMaximumRate) upper=std::min(upper,bounds.maximumRateFt3S*result.elapsedSeconds);
    if (upper<lower-1e-9) {result.reason=Reason::MainRateContradiction;return result;}
    const int64_t first=static_cast<int64_t>(std::ceil((lower-phaseError-result.rawPhaseDelta)/5));
    const int64_t last=static_cast<int64_t>(std::floor((upper+phaseError-result.rawPhaseDelta)/5));
    result.candidates=std::max(int64_t(0),last-first+1);
    if (!result.candidates) {result.reason=Reason::SecondaryMainContradiction;return result;}
    result.firstTurnOffset=first;result.lastTurnOffset=last;
    result.minimumFt3=std::max(lower,result.rawPhaseDelta+5*first-phaseError);
    result.maximumFt3=std::min(upper,result.rawPhaseDelta+5*last+phaseError);
    if (result.candidates!=1) {
        result.status=Status::Ambiguous;result.reason=Reason::TurnCountUnresolved;return result;
    }
    const double estimate=result.rawPhaseDelta+5*first;
    if (estimate<=phaseError+1e-9) {
        result.status=Status::WithinNoise;result.reason=Reason::SecondaryNoise;return result;
    }
    if (estimate<lower-1e-9 || estimate>upper+1e-9) {
        result.status=Status::BoundedOnly;result.reason=Reason::UncertaintyTailsOnly;return result;
    }
    result.status=Status::Estimated;result.reason=Reason::UniqueUnderBounds;
    result.estimatedFt3=estimate;result.averageFt3S=estimate/result.elapsedSeconds;
    return result;
}
}
