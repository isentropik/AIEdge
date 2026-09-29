#pragma once
#include <cmath>
#include <cstddef>

namespace meter {
enum class RevolutionResult { Invalid, Inconsistent, Ambiguous, Ready };
// Prototype for nested mechanical registers. Each phase is on a 0..10 scale;
// valuePerRevolution is a physical quantity, never a decimal place index.
// The caller supplies an error bound on each observed dial position. This is
// not a claim that a model has been validated to that bound.
struct RevolutionDial { double valuePerRevolution, position, error; };
inline RevolutionResult reconstructRevolutions(const RevolutionDial* dials,
                                               std::size_t count,double& output) {
    if(!dials||!count||count>16)return RevolutionResult::Invalid;
    for(std::size_t i=0;i<count;++i){
        const auto& d=dials[i];
        if(!std::isfinite(d.valuePerRevolution)||d.valuePerRevolution<=0||
           !std::isfinite(d.position)||d.position<0||d.position>=10||
           !std::isfinite(d.error)||d.error<0||d.error>=.5)return RevolutionResult::Invalid;
        if(i){
            const double ratio=dials[i-1].valuePerRevolution/d.valuePerRevolution;
            if(!std::isfinite(ratio)||ratio<2||ratio>1000000||std::abs(ratio-std::round(ratio))>1e-9)
                return RevolutionResult::Invalid;
        }
    }
    double value=dials[count-1].position/10*dials[count-1].valuePerRevolution;
    const double error=dials[count-1].error/10*dials[count-1].valuePerRevolution;
    double low=-error,high=error;
    for(std::size_t i=count-1;i>0;--i){
        const double lowerPeriod=dials[i].valuePerRevolution;
        const double period=dials[i-1].valuePerRevolution;
        const double expected=dials[i-1].position/10*period;
        const double upperError=dials[i-1].error/10*period;
        const double epsilon=period*1e-12;
        // Candidates differ by a full turn of the lower register. Locate the
        // nearest one without enumerating all possible gear-ratio turns.
        const double turn=std::round((expected-value-(low+high)/2)/lowerPeriod);
        const double candidate=value+turn*lowerPeriod;
        auto overlaps=[&](double center){return center+low<=expected+upperError+epsilon&&center+high>=expected-upperError-epsilon;};
        if(!overlaps(candidate))return RevolutionResult::Inconsistent;
        if(overlaps(candidate-lowerPeriod)||overlaps(candidate+lowerPeriod))return RevolutionResult::Ambiguous;
        // Retain the common uncertainty interval through every higher dial;
        // pairwise agreement alone can admit mutually contradictory readings.
        low=std::fmax(low,expected-upperError-candidate);
        high=std::fmin(high,expected+upperError-candidate);
        if(low>high){const double middle=(low+high)/2;low=high=middle;}
        value=std::fmod(candidate,period);if(value<0)value+=period;
    }
    if(!std::isfinite(value))return RevolutionResult::Invalid;
    const double period=dials[0].valuePerRevolution;
    value=std::fmod(value+(low+high)/2,period);if(value<0)value+=period;
    output=value;return RevolutionResult::Ready;
}
}
