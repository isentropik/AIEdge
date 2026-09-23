#pragma once
#include "ImageArchiveUnifiedConfig.h"
#include "../jomjol_controlcamera/ConfigJournal.h"

namespace ImageArchive { namespace SettingsStore {
using ConfigJournal::Storage;
using ConfigJournal::Read;
using ConfigJournal::Result;
inline bool valid(const std::string& bytes){StartupConfig c;Destination d;return parseArchiveSettings(bytes,c,d);}
inline bool absent(Storage& disk,const std::string& path){std::string ignored;return disk.read(path,ignored)==Read::Missing;}
inline bool restore(Storage& disk,const std::string& path,bool existed,const std::string& before){
    if(existed)return ConfigJournal::verifiedWrite(disk,path,before);
    if(absent(disk,path))return true;
    return disk.remove(path)&&absent(disk,path);
}
// Caller serializes saves and startup reads. Fail closed on a damaged journal;
// never guess credentials or delete evidence that could be needed for recovery.
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
