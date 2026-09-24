#pragma once
#include "MeterAssumptions.h"
#include "../jomjol_controlcamera/ConfigJournal.h"

namespace meter { namespace AssumptionsStore {
using ConfigJournal::Storage;
using ConfigJournal::Read;
using ConfigJournal::Result;
inline bool valid(const std::string& bytes){Assumptions value;return parseAssumptions(bytes,value);}
inline bool absent(Storage& disk,const std::string& path){std::string ignored;return disk.read(path,ignored)==Read::Missing;}
inline bool restore(Storage& disk,const std::string& path,bool existed,const std::string& before){
    if(existed)return ConfigJournal::verifiedWrite(disk,path,before);
    if(absent(disk,path))return true;
    return disk.remove(path)&&absent(disk,path);
}
// Caller serializes saves and startup reads. Fail closed on a damaged journal;
// never guess physical flow bounds or delete evidence that could be needed for recovery.
inline Result recoverSettings(Storage& disk,const std::string& path){
    std::string record,prior,after,current;
    const auto read=disk.read(path+".journal",record);
    if(read==Read::Missing)return Result::Ok;
    if(read!=Read::Ok)return Result::IoError;
    if(!ConfigJournal::decode(record,prior,after)||!valid(after)||prior.empty())return Result::InvalidJournal;
    const bool existed=prior[0]=='1';
    if((!existed&&prior!="0")||(existed&&!valid(prior.substr(1))))return Result::InvalidJournal;
    const std::string before=existed?prior.substr(1):"";
    const auto status=disk.read(path,current);
    if(status==Read::Error)return Result::IoError;
    const bool intact=status==Read::Ok&&(current==after||(existed&&current==before));
    if(!intact){
        // An independently written, valid third revision is a conflict, not a
        // torn write. Preserve it and the journal for explicit reconciliation.
        if(status==Read::Ok&&valid(current))return Result::Conflict;
        if(!restore(disk,path,existed,before))return Result::IoError;
    }
    return disk.remove(path+".journal")?Result::Ok:Result::CleanupPending;
}
struct Snapshot {bool existed=false;std::string bytes;Assumptions value;};
// Read-only inspection for editing. Recovery belongs to the processing owner,
// never an HTTP GET. Missing is the explicit disabled default; damage is not.
inline Result inspect(Storage& disk,const std::string& path,Snapshot& output){
    std::string journal,bytes;
    const auto pending=disk.read(path+".journal",journal);
    if(pending==Read::Error)return Result::IoError;
    if(pending!=Read::Missing)return Result::Conflict;
    const auto status=disk.read(path,bytes);
    if(status==Read::Error)return Result::IoError;
    Snapshot next;
    if(status==Read::Ok){
        if(!parseAssumptions(bytes,next.value))return Result::Conflict;
        next.existed=true;next.bytes=bytes;
    }
    output=next;return Result::Ok;
}
// A successful save does not activate bounds in an existing accounting session.
// The processing owner must switch session and recovery namespace together.
inline Result commit(Storage& disk,const std::string& path,bool existed,
                     const std::string& before,const std::string& after){
    if(!valid(after)||(existed&&!valid(before))||(!existed&&!before.empty()))return Result::Conflict;
    const auto recovered=recoverSettings(disk,path);
    if(recovered!=Result::Ok)return recovered==Result::CleanupPending?Result::IoError:recovered;
    std::string current;const auto read=disk.read(path,current);
    if(read==Read::Error)return Result::IoError;
    if(existed?(read!=Read::Ok||current!=before):read!=Read::Missing)return Result::Conflict;
    if(existed&&before==after)return Result::Ok;
    const auto journal=path+".journal";
    if(!ConfigJournal::verifiedWrite(disk,journal,ConfigJournal::encode(existed?"1"+before:"0",after)))return Result::IoError;
    if(!ConfigJournal::verifiedWrite(disk,path,after)){
        if(restore(disk,path,existed,before))disk.remove(journal);
        return Result::IoError;
    }
    return disk.remove(journal)?Result::Ok:Result::CleanupPending;
}
}}
