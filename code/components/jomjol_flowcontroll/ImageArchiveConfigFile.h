#pragma once
#include "ImageArchiveConfig.h"
#include "ImageArchiveUnifiedConfig.h"
#include "ImageArchiveSettingsStore.h"
#include "../jomjol_controlcamera/FileConfigStorage.h"
#include "ImageArchiveTransport.h"
#include <cstdio>
#include <cerrno>
#include <sys/stat.h>

namespace ImageArchive {
enum class ConfigLoad { Disabled, Ready, Invalid, IoError };
enum class SmallFile { Ok, Missing, Invalid, IoError };
inline SmallFile readArchiveConfigFile(const std::string& path,size_t limit,std::string& out) {
    out.clear();struct stat info{};
    if(stat(path.c_str(),&info)!=0)return errno==ENOENT?SmallFile::Missing:SmallFile::IoError;
    if(!S_ISREG(info.st_mode)||info.st_size<=0||static_cast<uint64_t>(info.st_size)>limit)return SmallFile::Invalid;
    FILE* file=std::fopen(path.c_str(),"rb");if(!file)return SmallFile::IoError;
    std::string body;char bytes[256];bool valid=true;
    while(true){
        const size_t count=std::fread(bytes,1,sizeof(bytes),file);
        if(body.size()+count>limit){valid=false;break;}
        body.append(bytes,count);
        if(count<sizeof(bytes)){if(std::ferror(file))valid=false;break;}
    }
    if(std::fclose(file)!=0)valid=false;
    if(!valid)return SmallFile::IoError;
    if(body.empty())return SmallFile::Invalid;
    out=body;return SmallFile::Ok;
}
// Directory is a trusted firmware-selected configuration directory, not a
// request parameter. Interrupted unified saves are recovered before parsing.
// Caller holds the configuration/processing guard; credentials are never logged.
inline ConfigLoad loadArchiveConfig(const std::string& directory,StartupConfig& config,Destination& destination) {
    config=StartupConfig{};destination=Destination{};
    ConfigStorage::Files disk;
    const auto recovery=SettingsStore::recoverSettings(disk,directory+"/image-archive-settings.json");
    if(recovery!=ConfigJournal::Result::Ok)return ConfigLoad::IoError;
    std::string body;
    // A present unified document is authoritative, including invalid/disabled
    // documents. Never fall back to stale legacy credentials after a failed save.
    auto read=readArchiveConfigFile(directory+"/image-archive-settings.json",12288,body);
    if(read!=SmallFile::Missing){
        if(read==SmallFile::IoError)return ConfigLoad::IoError;
        StartupConfig next;Destination nextTarget;
        if(read!=SmallFile::Ok||!parseArchiveSettings(body,next,nextTarget))return ConfigLoad::Invalid;
        if(!next.enabled)return ConfigLoad::Disabled;
        config=next;destination=nextTarget;return ConfigLoad::Ready;
    }
    read=readArchiveConfigFile(directory+"/image-archive.json",1024,body);
    if(read==SmallFile::Missing)return ConfigLoad::Disabled;
    if(read==SmallFile::IoError)return ConfigLoad::IoError;
    StartupConfig next;
    if(read!=SmallFile::Ok||!parseStartupConfig(body,next))return ConfigLoad::Invalid;
    if(!next.enabled)return ConfigLoad::Disabled;
    Destination target;target.host=next.host;target.port=next.port;target.timeoutMs=next.timeoutMs;
    read=readArchiveConfigFile(directory+"/image-archive-ca.pem",8192,target.certificatePem);
    if(read!=SmallFile::Ok)return read==SmallFile::IoError?ConfigLoad::IoError:ConfigLoad::Invalid;
    read=readArchiveConfigFile(directory+"/image-archive-token.txt",258,target.token);
    if(read!=SmallFile::Ok)return read==SmallFile::IoError?ConfigLoad::IoError:ConfigLoad::Invalid;
    // Permit one editor-added LF or CRLF, not arbitrary whitespace.
    if(!target.token.empty()&&target.token.back()=='\n'){
        target.token.pop_back();if(!target.token.empty()&&target.token.back()=='\r')target.token.pop_back();
    }
    if(!validArchiveDestination(target))return ConfigLoad::Invalid;
    // TLS performs cryptographic certificate parsing/validation before upload.
    config=next;destination=target;return ConfigLoad::Ready;
}
}
