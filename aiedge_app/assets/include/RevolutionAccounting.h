#pragma once
#include "MeterCumulative.h"
#include <string>
#include <vector>
#include <set>

namespace meter {
// Generic interval adapter for the same nested mechanical dial scales used by
// RevolutionReading. Quantity fields inherited from Interval/CumulativeResult
// are in the caller's source unit, regardless of the legacy Ft3 member names.
// There are no accounting roles. Every dial constrains the same physical motion.
struct RevolutionObservation {
    std::vector<double> positions;
    // Empty mask preserves the existing all-observed API. Unknown phases are never reused.
    std::vector<unsigned char> observed;
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
                long double upper,std::vector<Range>& result,bool& limited,
                const std::vector<unsigned char>& mask={},long double lower=0) const {
        limited=false;result={{lower,upper,0}};
        for(std::size_t index=0;index<assumptions.periods.size();++index) {
            if(!mask.empty()&&!mask[index])continue;
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
        if(!frame.observed.empty()&&frame.observed.size()!=frame.positions.size())return false;
        bool any=false;std::size_t largest=0;
        for(std::size_t i=0;i<frame.positions.size();++i) {
            if(!frame.observed.empty()&&frame.observed[i]>1)return false;
            if(frame.observed.empty()||frame.observed[i]) {
                if(!validPosition(frame.positions[i]))return false;
                if(!any)largest=i;any=true;
            }
        }
        // Cumulative turn phase is always the configured smallest dial.
        if(!any||(!frame.observed.empty()&&!frame.observed.back()))return false;
        std::vector<Range> possible;bool limited;
        const long double upper=frame.observed.empty()?assumptions.periods[0]:assumptions.periods[largest];
        return ranges(frame.positions,1,upper,possible,limited,frame.observed)&&!possible.empty();
    }
    bool full(const RevolutionObservation& frame) const {
        return frame.observed.empty()||std::all_of(frame.observed.begin(),frame.observed.end(),[](unsigned char x){return x==1;});
    }

    Interval operator()(const RevolutionObservation& before,const RevolutionObservation& after,const Bounds&,const int64_t* provenTurns=nullptr) const {
        Interval out;
        if(!valid)return out;
        out.reason=Reason::CaptureTimeRequired;
        if(before.captureUs<0||after.captureUs<=before.captureUs)return out;
        out.reason=Reason::ClockDomainMismatch;
        if(before.clockId.empty()||before.clockId!=after.clockId)return out;
        if(!accepts(before)||!accepts(after)){out.status=Status::Review;out.reason=Reason::MainInconsistent;return out;}
        out.elapsedSeconds=static_cast<double>(after.captureUs-before.captureUs)/1000000;
        std::vector<double> phases(before.positions.size(),0);
        std::vector<unsigned char> common(before.positions.size(),0);std::size_t largest=before.positions.size();
        for(std::size_t i=0;i<before.positions.size();++i) {
            common[i]=(before.observed.empty()||before.observed[i])&&(after.observed.empty()||after.observed[i]);
            if(common[i]) {if(largest==before.positions.size())largest=i;phases[i]=after.positions[i]-before.positions[i];}
        }
        if(!common.back()||largest==before.positions.size())return out;
        out.rawPhaseDelta=phases.back()*assumptions.periods.back()/10;
        const long double upper=assumptions.hasMaximumRate?
            static_cast<long double>(assumptions.maximumRate)*out.elapsedSeconds:assumptions.periods[largest];
        if(!std::isfinite(upper)||upper>std::numeric_limits<double>::max())return out;
        std::vector<Range> possible;bool limited;
        long double searchLow=0,searchHigh=upper;
        if(provenTurns) {
            // Restrict work using a caller-proved integer lift. Endpoint error
            // remains relative to the original anchor, never summed per step.
            if(std::abs(static_cast<long double>(*provenTurns))>4503599627370495.0L)return out;
            const long double period=assumptions.periods.back();
            const long double center=static_cast<long double>(phases.back())*period/10+
                                     static_cast<long double>(*provenTurns)*period;
            const long double error=2*assumptions.errors.back()*period/10+2*period*1e-12L;
            searchLow=std::max(0.0L,center-error);searchHigh=std::min(upper,center+error);
            if(!std::isfinite(searchLow)||!std::isfinite(searchHigh)||searchLow>searchHigh) {
                out.status=Status::Review;out.reason=Reason::MainRateContradiction;return out;
            }
        }
        if(!ranges(phases,2,searchHigh,possible,limited,common,searchLow)){out.reason=Reason::TurnCountUnresolved;return out;}
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

// Keep the finite set of possible integer lifts after an ambiguous interval.
// Discarding that set loses intervening observations and can introduce turns
// that no sequence of adjacent observations permits. This deliberately retains
// a superset of physical paths: it does not assume independent endpoint errors
// are an exact jointly feasible path, nor sum clipped noisy volume increments.
class RevolutionBranchCumulative {
    RevolutionIntervalResolver resolver;
    FixedAnchorCumulative<RevolutionObservation,RevolutionIntervalResolver> unbounded;
    bool bounded;
    RevolutionObservation anchor{}, previous{};
    std::set<int64_t> offsets;
    CumulativeResult result;
    static constexpr std::size_t maximumBranches=128;
    static bool usable(const Interval& x) {
        return x.status!=Status::Invalid && x.status!=Status::Review &&
            std::isfinite(x.minimumFt3) && std::isfinite(x.maximumFt3) &&
            x.minimumFt3<=x.maximumFt3;
    }
public:
    explicit RevolutionBranchCumulative(const RevolutionAssumptions& a):
        resolver(a),unbounded(resolver),bounded(a.hasMaximumRate){}
    const CumulativeResult& current() const {return bounded?result:unbounded.current();}
    void stale() {
        if(!bounded){unbounded.stale();return;}
        result.current=false;result.estimatedFt3=std::numeric_limits<double>::quiet_NaN();
    }
    void reset(const RevolutionObservation& frame) {
        if(!bounded){unbounded.reset(frame);return;}
        anchor=previous=frame;offsets={0};result=CumulativeResult{};
        result.available=result.current=true;
        result.anchorUs=result.throughUs=frame.captureUs;result.status=Status::WithinNoise;
    }
    bool observe(const RevolutionObservation& frame,const Bounds& bounds) {
        if(!bounded)return unbounded.observe(frame,bounds);
        if(!result.available||frame.clockId!=anchor.clockId||frame.captureUs<=result.throughUs)return false;
        const Interval step=resolver(previous,frame,bounds);
        if(!usable(step)||step.candidates<1||step.firstTurnOffset>step.lastTurnOffset||
            static_cast<long double>(step.lastTurnOffset)-step.firstTurnOffset>=maximumBranches)return false;
        std::set<int64_t> proposed;
        for(int64_t delta=step.firstTurnOffset;;++delta) {
            const Interval exactStep=resolver(previous,frame,bounds,&delta);
            if(exactStep.status==Status::Invalid)return false; // Work/numeric limit: never prune unknown paths.
            if(usable(exactStep)) {
                for(int64_t prior:offsets) {
                    if((delta>0&&prior>std::numeric_limits<int64_t>::max()-delta)||
                       (delta<0&&prior<std::numeric_limits<int64_t>::min()-delta))return false;
                    proposed.insert(prior+delta);
                    if(proposed.size()>maximumBranches)return false;
                }
            }
            if(delta==step.lastTurnOffset)break;
        }
        std::set<int64_t> next;
        Interval unique;
        double low=std::numeric_limits<double>::infinity(),high=0;
        for(int64_t offset:proposed) {
            const Interval whole=resolver(anchor,frame,bounds,&offset);
            if(whole.status==Status::Invalid)return false;
            if(!usable(whole)||whole.maximumFt3<result.minimumFt3)continue;
            next.insert(offset);unique=whole;
            low=std::min(low,whole.minimumFt3);high=std::max(high,whole.maximumFt3);
        }
        if(next.empty())return false;
        CumulativeResult candidate=result;
        candidate.current=true;candidate.throughUs=frame.captureUs;
        candidate.minimumFt3=std::max(result.minimumFt3,low);candidate.maximumFt3=high;
        candidate.status=next.size()==1?unique.status:Status::Ambiguous;
        candidate.estimatedFt3=next.size()==1?unique.estimatedFt3:std::numeric_limits<double>::quiet_NaN();
        if(std::isfinite(candidate.estimatedFt3)&&candidate.estimatedFt3<candidate.minimumFt3) {
            candidate.estimatedFt3=std::numeric_limits<double>::quiet_NaN();candidate.status=Status::BoundedOnly;
        }
        offsets=std::move(next);previous=frame;result=candidate;
        return true;
    }
};

class RevolutionCumulative {
    RevolutionIntervalResolver resolver;
    RevolutionBranchCumulative tracker;
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
    explicit RevolutionCumulative(const RevolutionAssumptions& assumptions):resolver(assumptions),tracker(assumptions){}
    bool configured() const {return resolver.configured();}
    const CumulativeResult& current() const {return published;}
    bool reset(const RevolutionObservation& frame) {
        if(!resolver.full(frame)||!resolver.accepts(frame))return false;
        tracker.reset(frame);highestEstimate=std::numeric_limits<double>::quiet_NaN();publish();return true;
    }
    bool observe(const RevolutionObservation& frame) {
        if(!resolver.accepts(frame)||!tracker.observe(frame,Bounds{})){stale();return false;}
        publish();return true;
    }
    void stale(){tracker.stale();published=tracker.current();}
};
}
