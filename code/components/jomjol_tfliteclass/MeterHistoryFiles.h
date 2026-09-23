#pragma once
#include "MeterHistory.h"
#include <dirent.h>
#include <sys/stat.h>
#include <cstdio>
#include <cerrno>
namespace meter {
// Caller owns processing/storage access. Directory and prefix are fixed firmware
// paths, never request-supplied. Completed segments only, not the active slot.
inline HistorySummary readSegmentHistory(const std::string& directory,const std::string& prefix,
        const std::string& model,const std::string& calibration,const Bounds& bounds){
    HistorySummary failed;
    DIR* dir=opendir(directory.c_str());
    if(!dir){failed.reason="directory_unavailable";return failed;}
    std::vector<Checkpoint> records;size_t examined=0;const char* failure=nullptr;
    const std::string marker=prefix+".segment-";
    while(true){
        errno=0;auto* entry=readdir(dir);
        if(!entry){if(errno)failure="directory_read_failed";break;}
        if(++examined>512){failure="directory_scan_limit";break;}
        const std::string name=entry->d_name;
        if(name.compare(0,marker.size(),marker)!=0)continue;
        if(records.size()==64){failure="record_limit_exceeded";break;}
        if(name.size()>180 || name.find('/')!=std::string::npos || name.find('\\')!=std::string::npos){failure="invalid_record_name";break;}
        const auto path=directory+"/"+name;struct stat info{};
        if(stat(path.c_str(),&info)!=0||!S_ISREG(info.st_mode)||info.st_size!=301){failure="invalid_record_file";break;}
        FILE* file=std::fopen(path.c_str(),"rb");
        if(!file){failure="record_read_failed";break;}
        char bytes[302];const auto size=std::fread(bytes,1,sizeof(bytes),file);
        const bool error=std::ferror(file)!=0;const int closed=std::fclose(file);
        if(error||closed||size!=301){failure="record_read_failed";break;}
        Checkpoint record;
        if(!decodeCheckpoint(std::string(bytes,size),model,calibration,bounds,record)||!record.hasSegment){failure="invalid_or_incompatible_record";break;}
        const auto expected=marker+std::to_string(record.anchor.clockId)+"-"+
            std::to_string(record.anchor.captureUs)+"-"+std::to_string(record.reference.captureUs)+".bin";
        if(name!=expected){failure="record_name_mismatch";break;}
        records.push_back(record);
    }
    if(closedir(dir)!=0&&!failure)failure="directory_close_failed";
    if(failure){failed.reason=failure;return failed;}
    return summarizeSegments(records);
}
}
