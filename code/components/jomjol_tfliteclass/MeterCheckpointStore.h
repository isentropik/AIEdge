#pragma once
#include "MeterCheckpoint.h"

namespace meter {
enum class StoreStatus { Empty, Ready, RecoveredOlder, IoError, Corrupt, Incompatible, Conflict, Saved };
inline const char* storeStatusName(StoreStatus state) {
    switch(state) {
        case StoreStatus::Empty:return "empty";
        case StoreStatus::Ready:return "loaded";
        case StoreStatus::RecoveredOlder:return "recovered_remaining_copy";
        case StoreStatus::IoError:return "io_error";
        case StoreStatus::Corrupt:return "corrupt";
        case StoreStatus::Incompatible:return "incompatible";
        case StoreStatus::Conflict:return "conflict";
        case StoreStatus::Saved:return "saved_and_verified";
    }
    return "unknown";
}
struct StoredCheckpoint {
    StoreStatus status=StoreStatus::Empty;
    Checkpoint checkpoint;
    uint64_t generation=0;
    int slot=-1;
};
inline std::string storeEnvelope(const std::string& checkpoint,uint64_t generation) {
    std::string bytes="MTRS0001";append64(bytes,generation);bytes+=checkpoint;
    ConfigJournal::append32(bytes,ConfigJournal::crc(bytes));return bytes;
}
inline bool readEnvelope(const std::string& bytes,uint64_t& generation) {
    if((bytes.size()!=249&&bytes.size()!=321)||bytes.compare(0,8,"MTRS0001")||
       ConfigJournal::crc(bytes.substr(0,bytes.size()-4))!=ConfigJournal::get32(bytes,bytes.size()-4))return false;
    generation=read64(bytes,8);return generation!=0;
}
inline StoredCheckpoint loadCheckpoint(ConfigJournal::Storage& storage,const std::string& path,
        const std::string& model,const std::string& calibration,const Bounds& bounds) {
    StoredCheckpoint result;
    std::string bytes[2];uint64_t generations[2]={0,0};bool valid[2]={false,false};
    int damaged=0,present=0;
    for(int i=0;i<2;++i) {
        const auto status=storage.read(path+"."+std::to_string(i),bytes[i]);
        if(status==ConfigJournal::Read::Error){result.status=StoreStatus::IoError;return result;}
        if(status==ConfigJournal::Read::Ok){++present;valid[i]=readEnvelope(bytes[i],generations[i]);if(!valid[i])++damaged;}
    }
    if(!present)return result;
    if(!valid[0]&&!valid[1]){result.status=StoreStatus::Corrupt;return result;}
    if(valid[0]&&valid[1]&&generations[0]==generations[1]&&bytes[0]!=bytes[1]) {
        result.status=StoreStatus::Conflict;return result;
    }
    const int newest=valid[1]&&(!valid[0]||generations[1]>generations[0]) ? 1:0;
    // Never fall back to an older compatible identity when the newest intact
    // record belongs to a different model/calibration or has invalid semantics.
    if(!decodeCheckpoint(bytes[newest].substr(16,bytes[newest].size()-20),model,calibration,bounds,result.checkpoint)) {
        result.status=StoreStatus::Incompatible;return result;
    }
    result.slot=newest;result.generation=generations[newest];
    result.status=damaged ? StoreStatus::RecoveredOlder : StoreStatus::Ready;return result;
}
inline StoreStatus saveCheckpoint(ConfigJournal::Storage& storage,const std::string& path,
                                  const Checkpoint& value) {
    const auto encoded=encodeCheckpoint(value);if(encoded.empty())return StoreStatus::Incompatible;
    const auto previous=loadCheckpoint(storage,path,value.modelHash,value.calibrationHash,value.bounds);
    if(previous.status!=StoreStatus::Empty&&previous.status!=StoreStatus::Ready&&previous.status!=StoreStatus::RecoveredOlder)
        return previous.status;
    if(previous.generation==std::numeric_limits<uint64_t>::max())return StoreStatus::Conflict;
    const int target=previous.slot==0 ? 1:0;
    const std::string record=storeEnvelope(encoded,previous.generation+1);
    // The newest valid slot is never overwritten by this operation.
    if(!ConfigJournal::verifiedWrite(storage,path+"."+std::to_string(target),record))return StoreStatus::IoError;
    return StoreStatus::Saved;
}
}
