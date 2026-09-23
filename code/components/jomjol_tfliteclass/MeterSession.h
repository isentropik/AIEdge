#pragma once
#include "MeterAccounting.h"
#include "MeterCumulative.h"

namespace meter {
enum class SessionState { Empty, Baseline, Interval, Rejected, Restarted, Pending };
inline const char* sessionStateName(SessionState state) {
    switch(state) {
        case SessionState::Empty:return "empty";
        case SessionState::Baseline:return "baseline";
        case SessionState::Interval:return "interval";
        case SessionState::Rejected:return "rejected";
        case SessionState::Restarted:return "restart_gap";
        case SessionState::Pending:return "awaiting_reading";
    }
    return "unknown";
}
inline const char* intervalStatusName(Status status) {
    switch(status) {
        case Status::Invalid:return "invalid";
        case Status::Review:return "review_required";
        case Status::Ambiguous:return "ambiguous_turn_count";
        case Status::WithinNoise:return "within_noise";
        case Status::BoundedOnly:return "bounded_only";
        case Status::Estimated:return "estimated_under_bounds";
    }
    return "unknown";
}
struct SessionResult {
    SessionState state=SessionState::Empty;
    Interval interval;
    uint64_t observed=0, rejected=0;
    bool hasReference=false;
    int64_t referenceCaptureUs=0;
    int64_t intervalStartUs=0;
    bool hasObservation=false;
    Frame observation{};
    Bounds assumptions;
    bool referencePersisted=false;
    const char* persistenceState="not_initialized";
    CumulativeResult cumulative,previousSegment;
    uint64_t previousSegmentBoot=0;
    bool cumulativePersisted=false;
    bool hasRestartGap=false;
    Frame beforeRestart{},afterRestart{};
};

// One owner under the controller processing guard. Cumulative bounds apply only
// since the explicit same-boot anchor; reference persistence does not restore it.
class Session {
    Frame reference{};
    Bounds bounds;
    SessionResult result;
    bool restoredReference=false;
    Cumulative cumulative;
    void accept(const Frame& frame) {
        reference=frame;result.hasReference=true;
        result.referenceCaptureUs=frame.captureUs;
    }
public:
    explicit Session(const Bounds& value=Bounds()): bounds(value) {result.assumptions=value;}
    const SessionResult& current() const { return result; }
    bool cumulativeAnchor(Frame& frame) const {return cumulative.anchorFrame(frame);}
    void restorePreviousSegment(const CumulativeResult& prior,uint64_t boot){
        result.previousSegment=prior;result.previousSegment.current=false;result.previousSegmentBoot=boot;
    }
    bool referenceFrame(Frame& frame) const {
        if (!result.hasReference) return false;
        frame=reference;return true;
    }
    bool restoreReference(const Frame& frame) {
        if (result.hasReference || result.observed) return false;
        Session checked(bounds);checked.observe(frame);
        if (checked.current().state!=SessionState::Baseline) return false;
        accept(frame);restoredReference=true;
        result.state=SessionState::Restarted;
        result.interval=Interval();result.interval.reason=Reason::ClockDomainMismatch;
        return true;
    }
    void begin() {
        cumulative.stale();result.cumulative=cumulative.current();
        result.state=SessionState::Pending;result.interval=Interval();
        result.intervalStartUs=0;
        result.hasObservation=false;
    }
    void reject(Reason reason,bool keepObservation=false) {
        cumulative.stale();result.cumulative=cumulative.current();
        ++result.observed;++result.rejected;
        result.state=SessionState::Rejected;
        result.interval=Interval();result.interval.reason=reason;
        result.intervalStartUs=0;
        if (!keepObservation) result.hasObservation=false;
    }
    void observe(const Frame& frame) {
        result.observation=frame;result.hasObservation=true;
        if (!std::isfinite(bounds.mainDial) || bounds.mainDial<0 || bounds.mainDial>=.5 ||
            !std::isfinite(bounds.secondaryDial) || bounds.secondaryDial<0 || bounds.secondaryDial>=.5 ||
            (bounds.hasMaximumRate && (!std::isfinite(bounds.maximumRateFt3S) || bounds.maximumRateFt3S<0))) {
            reject(Reason::InvalidBounds,true);return;
        }
        // Validate a single frame using the same rules as interval accounting.
        // A rejected frame never replaces the last usable reference.
        if (!frame.captureTimeValid || frame.captureUs<=0 || !frame.clockId) {
            reject(Reason::CaptureTimeRequired,true);return;
        }
        double total;
        if (!reconstruct(frame.main,total)) {reject(Reason::MainUnknown,true);return;}
        if (!consistent(frame.main,bounds.mainDial)) {reject(Reason::MainInconsistent,true);return;}
        if (!validPosition(frame.secondary)) {reject(Reason::SecondaryUnknown,true);return;}
        if (!result.hasReference || restoredReference || frame.clockId!=reference.clockId) {
            ++result.observed;
            result.state=result.hasReference ? SessionState::Restarted : SessionState::Baseline;
            result.interval=Interval();result.interval.reason=Reason::ClockDomainMismatch;
            result.intervalStartUs=0;
            if(result.hasReference){
                result.hasRestartGap=true;
                result.beforeRestart=reference;result.afterRestart=frame;
            }
            accept(frame);restoredReference=false;
            cumulative.reset(frame);result.cumulative=cumulative.current();return;
        }
        const Interval candidate=resolve(reference,frame,bounds);
        ++result.observed;result.interval=candidate;
        result.intervalStartUs=reference.captureUs;
        if (candidate.status==Status::Invalid || candidate.status==Status::Review) {
            cumulative.stale();result.cumulative=cumulative.current();
            ++result.rejected;result.state=SessionState::Rejected;return;
        }
        if(!cumulative.observe(frame,bounds)) {
            cumulative.stale();result.cumulative=cumulative.current();
            ++result.rejected;result.state=SessionState::Rejected;
            result.interval=Interval();result.interval.reason=Reason::CumulativeContradiction;
            return;
        }
        result.cumulative=cumulative.current();
        result.state=SessionState::Interval;
        accept(frame);
    }
};
}
