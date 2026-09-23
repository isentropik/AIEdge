#pragma once
#include "MeterCheckpoint.h"
#include <vector>

namespace meter {
struct HistorySummary {
    bool valid=false;
    const char* reason="empty_history";
    size_t segments=0,duplicates=0;
    double coveredMinimumFt3=0,coveredMaximumFt3=0;
    // Covered segments do not establish continuity or a lifetime total.
    bool lifetimeComplete=false;
};
inline bool sameFrame(const Frame& a,const Frame& b){
    if(a.clockId!=b.clockId||a.captureUs!=b.captureUs||a.captureTimeValid!=b.captureTimeValid||a.secondary!=b.secondary)return false;
    for(int i=0;i<5;++i)if(a.main[i]!=b.main[i])return false;
    return true;
}
inline HistorySummary summarizeSegments(const std::vector<Checkpoint>& records){
    HistorySummary out;
    if(records.empty())return out;
    if(records.size()>64){out.reason="record_limit_exceeded";return out;}
    std::vector<const Checkpoint*> unique;
    const auto& identity=records.front();
    for(const auto& item:records){
        if(!item.hasSegment||!checkpointValid(item)){out.reason="invalid_segment";return out;}
        if(item.modelHash!=identity.modelHash||item.calibrationHash!=identity.calibrationHash||
           item.bounds.mainDial!=identity.bounds.mainDial||item.bounds.secondaryDial!=identity.bounds.secondaryDial||
           item.bounds.hasMaximumRate!=identity.bounds.hasMaximumRate||item.bounds.maximumRateFt3S!=identity.bounds.maximumRateFt3S){
            out.reason="incompatible_segments";return out;
        }
        bool merged=false;
        for(auto& old:unique){
            if(old->anchor.clockId!=item.anchor.clockId||old->anchor.captureUs!=item.anchor.captureUs)continue;
            if(!sameFrame(old->anchor,item.anchor)){out.reason="anchor_conflict";return out;}
            if(old->reference.captureUs==item.reference.captureUs){
                if(!sameFrame(old->reference,item.reference)||old->minimumFt3!=item.minimumFt3){out.reason="endpoint_conflict";return out;}
            } else {
                const auto* early=old->reference.captureUs<item.reference.captureUs?old:&item;
                const auto* late=early==old?&item:old;
                const auto interval=resolve(early->reference,late->reference,late->bounds);
                if(late->minimumFt3<early->minimumFt3||interval.status==Status::Invalid||interval.status==Status::Review){
                    out.reason="segment_progression_conflict";return out;
                }
                old=late;
            }
            ++out.duplicates;merged=true;break;
        }
        if(!merged)unique.push_back(&item);
    }
    // Different anchors in one clock domain must not overlap. A shared endpoint
    // is allowed only when both copies carry the identical physical reading.
    for(size_t i=0;i<unique.size();++i)for(size_t j=i+1;j<unique.size();++j){
        const auto* a=unique[i];const auto* b=unique[j];
        if(a->anchor.clockId!=b->anchor.clockId)continue;
        if(a->anchor.captureUs>b->anchor.captureUs)std::swap(a,b);
        if(a->reference.captureUs>b->anchor.captureUs ||
           (a->reference.captureUs==b->anchor.captureUs&&!sameFrame(a->reference,b->anchor))){
            out.reason="overlapping_segments";return out;
        }
    }
    for(const auto* item:unique){
        CumulativeResult segment;
        if(!checkpointSegment(*item,segment)){out.reason="invalid_segment";return out;}
        out.coveredMinimumFt3+=segment.minimumFt3;out.coveredMaximumFt3+=segment.maximumFt3;
    }
    out.segments=unique.size();out.valid=true;out.reason="covered_segments_only";
    return out;
}
inline HistorySummary decodeSegmentHistory(const std::vector<std::string>& bytes,
        const std::string& model,const std::string& calibration,const Bounds& bounds){
    HistorySummary failed;
    if(bytes.size()>64){failed.reason="record_limit_exceeded";return failed;}
    std::vector<Checkpoint> records;records.reserve(bytes.size());
    for(const auto& record:bytes){
        Checkpoint item;
        if(!decodeCheckpoint(record,model,calibration,bounds,item)||!item.hasSegment){
            failed.reason="invalid_or_incompatible_record";return failed;
        }
        records.push_back(item);
    }
    return summarizeSegments(records);
}

}
