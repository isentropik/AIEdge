#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include "ReadingFormat.h"
#include "RevolutionReading.h"

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
    CumulativeContradiction, AccountingUnavailable, MainRegisterNoise,
    MainRegisterEstimate, MainRegisterTurnCountUnresolved
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
    // Compatibility mapping for existing installations until format storage and
    // activation are wired. Do not infer this mapping for other meters.
    const RegisterPlace places[]={{0,1000000},{1,100000},{2,10000},{3,1000},{4,100}};
    return reconstructRegister({places,5,1},values,5,total);
}
inline bool consistent(const double* values,std::size_t count,double tolerance) {
    if (!values || !count || count>16 || !std::isfinite(tolerance) || tolerance<0 || tolerance>=.5) return false;
    for (std::size_t i=0;i<count;++i) if (!validPosition(values[i])) return false;
    for (std::size_t i=0;i+1<count;++i) {
        double residual=std::numeric_limits<double>::infinity();
        for (int k=0;k<10;++k)
            residual=std::min(residual,circularDistance(k+values[i+1]/10,values[i],10));
        if (residual>tolerance+tolerance/10+1e-9) return false;
    }
    return true;
}
inline bool consistent(const double* values,double tolerance) {return consistent(values,5,tolerance);}
inline bool evaluateRegister(const ReadingFormat& format,const double* values,std::size_t count,double tolerance,double& total) {
    if(!validReadingFormat(format)||count!=format.count||!values)return false;
    if(decimalRegister(format))return consistent(values,count,tolerance)&&reconstructRegister(format,values,count,total);
    RevolutionDial dials[16];
    for(std::size_t i=0;i<count;++i)dials[i]={format.places[i].unitsPerStep*10,values[i],tolerance};
    double value;
    if(reconstructRevolutions(dials,count,value)!=RevolutionResult::Ready)return false;
    value*=format.multiplier;if(!std::isfinite(value))return false;
    total=value;return true;
}
struct RegisterFrameView {
    const double* main;
    std::size_t count;
    double secondary;
    int64_t captureUs;
    bool captureTimeValid;
    uint64_t clockId;
};
// Numeric volume fields in Interval use the supplied source unit in this API.
// Legacy *Ft3 member names remain for the existing gas-accounting adapter.
inline Interval resolveScaled(const RegisterFrameView& previous,const RegisterFrameView& current,
                              const Bounds& bounds,const ReadingFormat& format,double wheelUnitsPerTurn,
                              bool useWheel=true) {
    Interval result;
    if(!validReadingFormat(format)||previous.count!=format.count||current.count!=format.count||
       !std::isfinite(wheelUnitsPerTurn)||wheelUnitsPerTurn<=0) return result;
    const double lowestStep=format.places[format.count-1].unitsPerStep*format.multiplier;
    const double registerPeriod=format.places[0].unitsPerStep*10*format.multiplier;
    const double slack=lowestStep/100*numericalSlackFt3;
    const double epsilon=(useWheel?wheelUnitsPerTurn/5:lowestStep/100)*1e-9;
    if(!std::isfinite(lowestStep)||lowestStep<=0) return result;
    if (!std::isfinite(bounds.mainDial) || bounds.mainDial<0 || bounds.mainDial>=.5 ||
        (useWheel&&(!std::isfinite(bounds.secondaryDial) || bounds.secondaryDial<0 || bounds.secondaryDial>=.5)) ||
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
    if (!reconstructRegister(format,previous.main,previous.count,oldTotal) || !reconstructRegister(format,current.main,current.count,newTotal)) return result;
    if (!evaluateRegister(format,previous.main,previous.count,bounds.mainDial,oldTotal) || !evaluateRegister(format,current.main,current.count,bounds.mainDial,newTotal)) {
        result.status=Status::Review;result.reason=Reason::MainInconsistent;return result;
    }
    if(useWheel) {
        result.reason=Reason::SecondaryUnknown;
        if (!validPosition(previous.secondary) || !validPosition(current.secondary)) return result;
    }
    result.rawMainDelta=newTotal-oldTotal;
    result.rawPhaseDelta=useWheel?(current.secondary-previous.secondary)*(wheelUnitsPerTurn/10):std::numeric_limits<double>::quiet_NaN();
    const double mainError=2*bounds.mainDial*lowestStep+slack;
    const double phaseError=2*bounds.secondaryDial*(wheelUnitsPerTurn/10)+slack;
    result.status=Status::Review;
    if (result.rawMainDelta<-registerPeriod/2) {
        result.reason=Reason::RegisterRolloverOrReset;return result;
    }
    if (result.rawMainDelta+mainError<-epsilon) {result.reason=Reason::BackwardMain;return result;}
    const double lower=std::max(0.0,result.rawMainDelta-mainError);
    double upper=result.rawMainDelta+mainError;
    if (bounds.hasMaximumRate) upper=std::min(upper,bounds.maximumRateFt3S*result.elapsedSeconds);
    if (upper<lower-epsilon) {result.reason=Reason::MainRateContradiction;return result;}
    if(!useWheel) {
        result.minimumFt3=lower;
        const double maximum=bounds.hasMaximumRate?bounds.maximumRateFt3S*result.elapsedSeconds:
            std::numeric_limits<double>::infinity();
        // Endpoints alone cannot exclude a hidden whole-register revolution.
        if(!std::isfinite(maximum)||maximum>=result.rawMainDelta+registerPeriod-mainError-epsilon) {
            result.status=Status::Ambiguous;result.reason=Reason::MainRegisterTurnCountUnresolved;
            result.maximumFt3=std::isfinite(maximum)?maximum:std::numeric_limits<double>::quiet_NaN();
            return result;
        }
        result.maximumFt3=std::max(lower,upper);
        if(result.rawMainDelta<=mainError+epsilon) {
            result.status=Status::WithinNoise;result.reason=Reason::MainRegisterNoise;return result;
        }
        if(result.rawMainDelta>upper+epsilon) {
            result.status=Status::BoundedOnly;result.reason=Reason::UncertaintyTailsOnly;return result;
        }
        result.status=Status::Estimated;result.reason=Reason::MainRegisterEstimate;
        result.estimatedFt3=result.rawMainDelta;result.averageFt3S=result.rawMainDelta/result.elapsedSeconds;
        return result;
    }
    const double firstValue=std::ceil((lower-phaseError-result.rawPhaseDelta)/wheelUnitsPerTurn);
    const double lastValue=std::floor((upper+phaseError-result.rawPhaseDelta)/wheelUnitsPerTurn);
    // Bound before integer conversion, including the candidate-count subtraction.
    if(!std::isfinite(firstValue)||!std::isfinite(lastValue)||
       std::abs(firstValue)>4503599627370495.0||std::abs(lastValue)>4503599627370495.0){
        result.status=Status::Invalid;result.reason=Reason::InvalidBounds;return result;
    }
    const int64_t first=static_cast<int64_t>(firstValue),last=static_cast<int64_t>(lastValue);
    result.candidates=std::max(int64_t(0),last-first+1);
    if (!result.candidates) {result.reason=Reason::SecondaryMainContradiction;return result;}
    result.firstTurnOffset=first;result.lastTurnOffset=last;
    result.minimumFt3=std::max(lower,result.rawPhaseDelta+wheelUnitsPerTurn*first-phaseError);
    result.maximumFt3=std::min(upper,result.rawPhaseDelta+wheelUnitsPerTurn*last+phaseError);
    if (result.candidates!=1) {
        result.status=Status::Ambiguous;result.reason=Reason::TurnCountUnresolved;return result;
    }
    const double estimate=result.rawPhaseDelta+wheelUnitsPerTurn*first;
    if (estimate<=phaseError+epsilon) {
        result.status=Status::WithinNoise;result.reason=Reason::SecondaryNoise;return result;
    }
    if (estimate<lower-epsilon || estimate>upper+epsilon) {
        result.status=Status::BoundedOnly;result.reason=Reason::UncertaintyTailsOnly;return result;
    }
    result.status=Status::Estimated;result.reason=Reason::UniqueUnderBounds;
    result.estimatedFt3=estimate;result.averageFt3S=estimate/result.elapsedSeconds;
    return result;
}
inline Interval resolveMainRegister(const RegisterFrameView& previous,const RegisterFrameView& current,
                                    const Bounds& bounds,const ReadingFormat& format) {
    return resolveScaled(previous,current,bounds,format,1,false);
}
inline Interval resolve(const Frame& previous,const Frame& current,const Bounds& bounds) {
    const RegisterPlace places[]={{0,1000000},{1,100000},{2,10000},{3,1000},{4,100}};
    const RegisterFrameView a{previous.main,5,previous.secondary,previous.captureUs,previous.captureTimeValid,previous.clockId};
    const RegisterFrameView b{current.main,5,current.secondary,current.captureUs,current.captureTimeValid,current.clockId};
    return resolveScaled(a,b,bounds,{places,5,1},secondaryRevolutionFt3);
}

}
