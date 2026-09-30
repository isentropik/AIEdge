#pragma once
#include "MeterCumulative.h"
#include <string>
#include <vector>

namespace meter {
// Generic interval adapter for the same nested mechanical dial scales used by
// RevolutionReading. Quantity fields inherited from Interval/CumulativeResult
// are in the caller's source unit, regardless of the legacy Ft3 member names.
// There are no accounting roles. Every dial constrains the same physical motion.
struct RevolutionObservation {
    std::vector<double> positions;
    int64_t captureUs=0;
    std::string clockId;
};
struct RevolutionAssumptions {
    std::vector<double> periods,errors;
    bool hasMaximumRate=false;
    double maximumRate=0;
};
class RevolutionIntervalResolver {
    struct Range {long double low,high; int64_t turn;};
    RevolutionAssumptions assumptions;
    static constexpr std::size_t maximumBranches=128;
    bool valid=false;
    static bool clockValid(const std::string& value) {
        if(value.empty()||value.size()>128)return false;
        for(char c:value)if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||
            (c>='0'&&c<='9')||c=='_'||c=='.'||c=='-'))return false;
        return true;
    }
    bool ranges(const std::vector<double>& phases,long double errorFactor,
                long double upper,std::vector<Range>& result,bool& limited) const {
        limited=false;result={{0,upper,0}};
        for(std::size_t index=0;index<assumptions.periods.size();++index) {
            const long double period=assumptions.periods[index];
            const long double phase=static_cast<long double>(phases[index])*period/10;
            const long double epsilon=period*1e-12L;
            // Scale-relative arithmetic slack, separate from model accuracy.
            const long double error=errorFactor*assumptions.errors[index]*period/10+epsilon;
            std::vector<Range> next;
            for(const auto& prior:result) {
                const long double first=std::ceil((prior.low-phase-error-epsilon)/period);
                const long double last=std::floor((prior.high-phase+error+epsilon)/period);
                if(first>last)continue;
                // Do not cast unbounded or inexact turn counts, nor silently
                // choose a candidate after exhausting the work budget.
                if(!std::isfinite(first)||!std::isfinite(last)||
                   std::abs(first)>4503599627370495.0L||std::abs(last)>4503599627370495.0L||
                   last-first+1>maximumBranches-next.size()) {limited=true;return false;}
                for(int64_t turn=static_cast<int64_t>(first);turn<=static_cast<int64_t>(last);++turn) {
                    const long double center=phase+period*turn;
                    long double low=std::max(prior.low,center-error),high=std::min(prior.high,center+error);
                    if(low>high) {
                        if(low-high>epsilon)continue;
                        // A boundary disagreement caused only by roundoff is
                        // represented by the boundary inside the prior range.
                        low=high=std::max(prior.low,std::min(prior.high,center));
                    }
                    next.push_back({low,high,turn});
                }
            }
            result=std::move(next);if(result.empty())return true;
        }
        return true;
    }
public:
    explicit RevolutionIntervalResolver(const RevolutionAssumptions& value):assumptions(value) {
        const auto count=assumptions.periods.size();
        if(!count||count>16||assumptions.errors.size()!=count||
            (assumptions.hasMaximumRate&&(!std::isfinite(assumptions.maximumRate)||assumptions.maximumRate<0)))return;
        for(std::size_t i=0;i<count;++i) {
            const double period=assumptions.periods[i],error=assumptions.errors[i];
            if(!std::isfinite(period)||period<=0||period/360<1e-12||
                !std::isfinite(error)||error<0||error>=.5)return;
            if(i) {
                const double ratio=assumptions.periods[i-1]/period;
                if(!std::isfinite(ratio)||ratio<2||ratio>1000000||std::abs(ratio-std::round(ratio))>1e-9)return;
            }
        }
        valid=true;
    }
    bool configured() const {return valid;}
    bool accepts(const RevolutionObservation& frame) const {
        if(!valid||frame.captureUs<0||!clockValid(frame.clockId)||frame.positions.size()!=assumptions.periods.size())return false;
        for(double value:frame.positions)if(!validPosition(value))return false;
        std::vector<Range> possible;bool limited;
        // Check every dial simultaneously, including ambiguous lower-dial
        // carries, without treating a point estimate as an exact observation.
        return ranges(frame.positions,1,assumptions.periods[0],possible,limited)&&!possible.empty();
    }
    Interval operator()(const RevolutionObservation& before,const RevolutionObservation& after,const Bounds&) const {
        Interval out;
        if(!valid)return out;
        out.reason=Reason::CaptureTimeRequired;
        if(before.captureUs<0||after.captureUs<=before.captureUs)return out;
        out.reason=Reason::ClockDomainMismatch;
        if(before.clockId.empty()||before.clockId!=after.clockId)return out;
        if(!accepts(before)||!accepts(after)){out.status=Status::Review;out.reason=Reason::MainInconsistent;return out;}
        out.elapsedSeconds=static_cast<double>(after.captureUs-before.captureUs)/1000000;
        std::vector<double> phases;
        for(std::size_t i=0;i<before.positions.size();++i)phases.push_back(after.positions[i]-before.positions[i]);
        out.rawPhaseDelta=phases.back()*assumptions.periods.back()/10;
        const long double upper=assumptions.hasMaximumRate?
            static_cast<long double>(assumptions.maximumRate)*out.elapsedSeconds:assumptions.periods[0];
        if(!std::isfinite(upper)||upper>std::numeric_limits<double>::max())return out;
        std::vector<Range> possible;bool limited;
        if(!ranges(phases,2,upper,possible,limited)){out.reason=Reason::TurnCountUnresolved;return out;}
        if(possible.empty()){out.status=Status::Review;out.reason=Reason::MainRateContradiction;return out;}
        out.minimumFt3=std::numeric_limits<double>::infinity();out.maximumFt3=0;
        out.firstTurnOffset=std::numeric_limits<int64_t>::max();out.lastTurnOffset=std::numeric_limits<int64_t>::min();
        for(const auto& range:possible) {
            out.minimumFt3=std::min(out.minimumFt3,static_cast<double>(range.low));
            out.maximumFt3=std::max(out.maximumFt3,static_cast<double>(range.high));
            out.firstTurnOffset=std::min(out.firstTurnOffset,range.turn);out.lastTurnOffset=std::max(out.lastTurnOffset,range.turn);
        }
        out.candidates=static_cast<int64_t>(possible.size());
        if(!assumptions.hasMaximumRate) {
            // All phases repeat after the largest register's whole revolution.
            // Endpoint images alone cannot bound those hidden repetitions.
            out.maximumFt3=std::numeric_limits<double>::infinity();out.candidates=0;
            out.lastTurnOffset=std::numeric_limits<int64_t>::max();
            out.status=Status::Ambiguous;out.reason=Reason::MainRegisterTurnCountUnresolved;return out;
        }
        if(possible.size()!=1){out.status=Status::Ambiguous;out.reason=Reason::TurnCountUnresolved;return out;}
        const double estimate=out.rawPhaseDelta+turnUnits()*out.firstTurnOffset;
        if(estimate<=phaseError(Bounds{})+epsilon()){out.status=Status::WithinNoise;out.reason=Reason::SecondaryNoise;return out;}
        if(estimate<out.minimumFt3-epsilon()||estimate>out.maximumFt3+epsilon()) {
            out.status=Status::BoundedOnly;out.reason=Reason::UncertaintyTailsOnly;return out;
        }
        out.status=Status::Estimated;out.reason=Reason::UniqueUnderBounds;
        out.estimatedFt3=estimate;out.averageFt3S=estimate/out.elapsedSeconds;return out;
    }
    double turnUnits() const {return assumptions.periods.back();}
    double phaseError(const Bounds&) const {return 2*assumptions.errors.back()*turnUnits()/10+epsilon();}
    double epsilon() const {return turnUnits()*1e-12;}
};
class RevolutionCumulative {
    RevolutionIntervalResolver resolver;
    FixedAnchorCumulative<RevolutionObservation,RevolutionIntervalResolver> tracker;
    CumulativeResult published;
    double highestEstimate=std::numeric_limits<double>::quiet_NaN();
    void publish() {
        published=tracker.current();
        // A point may move backwards inside overlapping error intervals even
        // when the physical lower bound is monotonic. Keep the range, but do
        // not publish a decreasing consumption point or silently clamp it.
        if(std::isfinite(published.estimatedFt3)) {
            if(std::isfinite(highestEstimate)&&published.estimatedFt3<highestEstimate) {
                published.estimatedFt3=std::numeric_limits<double>::quiet_NaN();
                published.status=Status::BoundedOnly;
            } else highestEstimate=published.estimatedFt3;
        }
    }
public:
    explicit RevolutionCumulative(const RevolutionAssumptions& assumptions):resolver(assumptions),tracker(resolver){}
    bool configured() const {return resolver.configured();}
    const CumulativeResult& current() const {return published;}
    bool reset(const RevolutionObservation& frame) {
        if(!resolver.accepts(frame))return false;
        tracker.reset(frame);highestEstimate=std::numeric_limits<double>::quiet_NaN();publish();return true;
    }
    bool observe(const RevolutionObservation& frame) {
        if(!resolver.accepts(frame)||!tracker.observe(frame,Bounds{})){stale();return false;}
        publish();return true;
    }
    void stale(){tracker.stale();published=tracker.current();}
};
}
