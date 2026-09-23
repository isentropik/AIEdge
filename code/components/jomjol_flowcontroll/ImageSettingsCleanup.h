#pragma once
#include "ImageSpoolRecovery.h"
#include "ImageSettingsFile.h"
namespace ImageArchive {
enum class SettingsCleanup { Removed, Referenced, Missing, Uncertain, IoError };
// Single owner only. Any unreadable or unclassified entry blocks deletion.
template<class Hash>
SettingsCleanup pruneSettings(const std::string& root,const std::string& hash) {
    std::string descriptor;
    const auto original=readSettingsFile<Hash>(root,hash,descriptor);
    if(original==SpoolResult::Missing)return SettingsCleanup::Missing;
    if(original!=SpoolResult::Saved)return SettingsCleanup::Uncertain;
    DIR* directory=opendir(root.c_str());if(!directory)return SettingsCleanup::IoError;
    bool complete=true,referenced=false;unsigned count=0;
    for(;;) {
        errno=0;auto* item=readdir(directory);
        if(!item){if(errno)complete=false;break;}
        std::string name=item->d_name;if(name=="."||name=="..")continue;
        if(++count>32){complete=false;break;}
        const auto path=root+"/"+name;
        struct stat info;
        if(stat(path.c_str(),&info)!=0||(info.st_mode&S_IFMT)!=S_IFREG){complete=false;break;}
        const bool spool=(name.size()==70&&name.substr(64)==".spool") ||
                         (name.size()==78&&name.substr(64)==".spool.pending");
        const bool settings=(name.size()==73&&name.substr(64)==".settings") ||
                            (name.size()==81&&name.substr(64)==".settings.pending");
        if(!validHash(name.substr(0,64))||(!spool&&!settings)){complete=false;break;}
        if(spool) {
            CaptureMetadata metadata;UploadRecord record;
            if(readSpoolFile<Hash>(path,metadata,record)!=SpoolResult::Saved || record.identity.capture!=name.substr(0,64)) {
                complete=false;break;
            }
            if(metadata.settingsHash==hash)referenced=true;
        } else {
            std::string checked;
            if(readSettingsPath<Hash>(path,name.substr(0,64),checked)!=SpoolResult::Saved){complete=false;break;}
        }
    }
    if(closedir(directory)!=0)complete=false;
    if(!complete)return SettingsCleanup::Uncertain;
    if(referenced)return SettingsCleanup::Referenced;
    std::string checked;
    if(readSettingsFile<Hash>(root,hash,checked)!=SpoolResult::Saved||checked!=descriptor)return SettingsCleanup::Uncertain;
    return std::remove((root+"/"+hash+".settings").c_str())==0 ? SettingsCleanup::Removed : SettingsCleanup::IoError;
}
}
