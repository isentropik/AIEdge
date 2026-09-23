#pragma once
#include "MeterSession.h"
#include <string>
#include <cstdio>

namespace meter {
inline const char* reasonName(Reason reason) {
    switch(reason) {
        case Reason::InvalidBounds:return "invalid_bounds";
        case Reason::CaptureTimeRequired:return "increasing_capture_time_required";
        case Reason::MainUnknown:return "main_reading_unavailable";
        case Reason::MainInconsistent:return "main_dials_inconsistent";
        case Reason::SecondaryUnknown:return "secondary_reading_unavailable";
        case Reason::RegisterRolloverOrReset:return "register_rollover_or_reset";
        case Reason::BackwardMain:return "backward_main_total";
        case Reason::MainRateContradiction:return "main_rate_contradiction";
        case Reason::SecondaryMainContradiction:return "secondary_main_contradiction";
        case Reason::TurnCountUnresolved:return "whole_turn_count_unresolved";
        case Reason::SecondaryNoise:return "within_secondary_noise";
        case Reason::UncertaintyTailsOnly:return "uncertainty_bounds_only";
        case Reason::UniqueUnderBounds:return "unique_under_assumed_bounds";
        case Reason::ClockDomainMismatch:return "clock_domain_mismatch";
        case Reason::CumulativeContradiction:return "cumulative_bounds_contradiction";
    }
    return "unknown";
}
inline std::string jsonNumber(double value) {
    if (!std::isfinite(value)) return "null";
    char buffer[48];std::snprintf(buffer,sizeof(buffer),"%.12g",value);return buffer;
}
inline std::string frameJson(const Frame& frame) {
    std::string out;
    out+="{\"main_dial_positions\":[";
    for(int i=0;i<5;++i) {if(i)out+=",";out+=jsonNumber(frame.main[i]);}
    out+="],\"secondary_dial_position\":"+jsonNumber(frame.secondary);
    out+=",\"position_scale\":\"0_to_10\",\"capture_us\":"+std::to_string(frame.captureUs);
    out+=",\"capture_time_valid\":";out+=frame.captureTimeValid ? "true" : "false";
    // String preserves the entire 64-bit identity in browser JSON clients.
    out+=",\"boot_identity\":\""+std::to_string(frame.clockId)+"\"}";
    return out;
}
inline std::string statusJson(const SessionResult& value) {
    const auto& interval=value.interval;
    const bool hasInterval=value.state==SessionState::Interval;
    const bool hasReason=hasInterval || value.state==SessionState::Rejected || value.state==SessionState::Restarted;
    std::string out="{\"state\":\"";
    out+=sessionStateName(value.state);
    out+="\",\"verified_accuracy\":false,\"clock\":\"monotonic_us_since_boot\"";
    out+=",\"reference_persisted\":";out+=value.referencePersisted ? "true" : "false";
    out+=",\"persistence_state\":\""+std::string(value.persistenceState)+"\"";
    out+=",\"observations\":"+std::to_string(value.observed)+",\"rejected\":"+std::to_string(value.rejected);
    out+=",\"reference_capture_us\":"+std::to_string(value.referenceCaptureUs);
    out+=",\"interval_start_us\":"+std::to_string(value.intervalStartUs);
    out+=",\"interval_status\":";
    out+=hasReason ? std::string("\"")+intervalStatusName(interval.status)+"\"" : "null";
    out+=",\"reason\":";
    out+=hasReason ? std::string("\"")+reasonName(interval.reason)+"\"" : "null";
    out+=",\"candidate_turn_counts\":"+std::to_string(interval.candidates);
    out+=",\"elapsed_seconds\":"+(hasInterval ? jsonNumber(interval.elapsedSeconds) : "null");
    out+=",\"minimum_ft3\":"+jsonNumber(interval.minimumFt3);
    out+=",\"maximum_ft3\":"+jsonNumber(interval.maximumFt3);
    out+=",\"estimated_ft3\":"+jsonNumber(interval.estimatedFt3);
    out+=",\"average_ft3_per_second\":"+jsonNumber(interval.averageFt3S);
    out+=",\"assumptions\":{\"main_dial_error\":"+jsonNumber(value.assumptions.mainDial);
    out+=",\"secondary_dial_error\":"+jsonNumber(value.assumptions.secondaryDial);
    out+=",\"maximum_ft3_per_second\":";
    out+=value.assumptions.hasMaximumRate ? jsonNumber(value.assumptions.maximumRateFt3S) : "null";
    out+="},\"raw_observation\":";
    if (!value.hasObservation) out+="null";
    else {
        out+=frameJson(value.observation);
    }
    out+=",\"restart_gap\":";
    if(!value.hasRestartGap)out+="null";
    else out+="{\"before\":"+frameJson(value.beforeRestart)+",\"after\":"+frameJson(value.afterRestart)+
        ",\"elapsed_seconds\":null,\"estimated_ft3\":null,\"resolved\":false,\"persisted\":false}";
    const auto& cumulative=value.cumulative;
    out+=",\"cumulative_since_anchor\":{\"available\":";
    out+=cumulative.available ? "true" : "false";
    out+=",\"current\":";out+=cumulative.current ? "true" : "false";
    out+=",\"persisted\":";out+=value.cumulativePersisted?"true":"false";
    out+=",\"anchor_us\":"+std::to_string(cumulative.anchorUs);
    out+=",\"through_us\":"+std::to_string(cumulative.throughUs);
    out+=",\"minimum_ft3\":"+(cumulative.available ? jsonNumber(cumulative.minimumFt3) : "null");
    out+=",\"maximum_ft3\":"+(cumulative.available ? jsonNumber(cumulative.maximumFt3) : "null");
    out+=",\"estimated_ft3\":"+jsonNumber(cumulative.estimatedFt3);
    out+=",\"status\":\""+std::string(intervalStatusName(cumulative.status))+"\"}";
    out+=",\"previous_segment\":";
    const auto& prior=value.previousSegment;
    if(!prior.available)out+="null";
    else out+="{\"boot_identity\":\""+std::to_string(value.previousSegmentBoot)+"\",\"current\":false,\"persisted\":true,\"anchor_us\":"+
        std::to_string(prior.anchorUs)+",\"through_us\":"+std::to_string(prior.throughUs)+
        ",\"minimum_ft3\":"+jsonNumber(prior.minimumFt3)+",\"maximum_ft3\":"+jsonNumber(prior.maximumFt3)+
        ",\"estimated_ft3\":"+jsonNumber(prior.estimatedFt3)+",\"included_in_current_segment\":false}";
    out+="}";return out;
}
}
