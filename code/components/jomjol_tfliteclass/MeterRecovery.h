#pragma once
#include "MeterCheckpointStore.h"
#include "MeterSession.h"

namespace meter {
// Single-owner coordinator. Persistent files never supply a consumptive delta
// across startup; session.restoreReference forces an explicit new baseline.
class Recovery {
    std::string path,model,calibration;
    Bounds bounds;
    std::string pendingSegmentPath,pendingSegmentBytes;
    bool initialized=false,writable=false;
    StoreStatus status=StoreStatus::Empty;
public:
    Recovery(std::string p,std::string m,std::string c,const Bounds& b=Bounds()):
        path(p),model(m),calibration(c),bounds(b) {}
    StoreStatus current() const {return status;}
    StoreStatus initialize(ConfigJournal::Storage& storage,Session& session) {
        if(initialized)return status;
        initialized=true;
        const auto& active=session.current().assumptions;
        if(active.mainDial!=bounds.mainDial||active.secondaryDial!=bounds.secondaryDial||
           active.hasMaximumRate!=bounds.hasMaximumRate||active.maximumRateFt3S!=bounds.maximumRateFt3S) {
            status=StoreStatus::Conflict;return status;
        }
        const auto loaded=loadCheckpoint(storage,path,model,calibration,bounds);
        status=loaded.status;
        writable=status==StoreStatus::Empty||status==StoreStatus::Ready||status==StoreStatus::RecoveredOlder;
        if(status==StoreStatus::Ready||status==StoreStatus::RecoveredOlder) {
            CumulativeResult prior;
            if(loaded.checkpoint.hasSegment && checkpointSegment(loaded.checkpoint,prior)) {
                session.restorePreviousSegment(prior,loaded.checkpoint.anchor.clockId);
                pendingSegmentPath=path+".segment-"+std::to_string(loaded.checkpoint.anchor.clockId)+
                    "-"+std::to_string(loaded.checkpoint.anchor.captureUs)+"-"+
                    std::to_string(loaded.checkpoint.reference.captureUs)+".bin";
                pendingSegmentBytes=encodeCheckpoint(loaded.checkpoint);
            }
            if(!session.restoreReference(loaded.checkpoint.reference)) {
                status=StoreStatus::Conflict;writable=false;
            }
        }
        return status;
    }
    StoreStatus save(ConfigJournal::Storage& storage,const Session& session) {
        if(!initialized)return StoreStatus::Conflict;
        if(!writable)return status;
        Checkpoint checkpoint;
        if(!session.referenceFrame(checkpoint.reference))return status;
        checkpoint.hasSegment=session.cumulativeAnchor(checkpoint.anchor);
        if(checkpoint.hasSegment)checkpoint.minimumFt3=session.current().cumulative.minimumFt3;
        checkpoint.modelHash=model;checkpoint.calibrationHash=calibration;checkpoint.bounds=bounds;
        // Preserve the prior segment before rotating either active checkpoint.
        // Single processing owner; existing evidence is never replaced or erased.
        if(!pendingSegmentBytes.empty()) {
            std::string existing;
            const auto read=storage.read(pendingSegmentPath,existing);
            if(read==ConfigJournal::Read::Error)status=StoreStatus::IoError;
            else if(read==ConfigJournal::Read::Ok && existing!=pendingSegmentBytes)status=StoreStatus::Conflict;
            else if(read==ConfigJournal::Read::Missing &&
                    !ConfigJournal::verifiedWrite(storage,pendingSegmentPath,pendingSegmentBytes))status=StoreStatus::IoError;
            else {pendingSegmentBytes.clear();pendingSegmentPath.clear();status=StoreStatus::Ready;}
            if(!pendingSegmentBytes.empty()){writable=false;return status;}
        }
        status=saveCheckpoint(storage,path,checkpoint);
        // An uncertain write requires fresh inspection, never an automatic retry.
        if(status!=StoreStatus::Saved)writable=false;
        return status;
    }
};
}
