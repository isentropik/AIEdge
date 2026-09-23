#pragma once
#include "ImageUploadQueue.h"
namespace ImageArchive {
static constexpr size_t MaxSettingsBytes=8192;
template<class Sha256>
bool validSettingsDescriptor(const std::string& hash,const std::string& descriptor,Sha256 sha) {
    if(!validHash(hash) || descriptor.empty() || descriptor.size()>MaxSettingsBytes ||
       descriptor.compare(0,20,"capture-settings-v1\n")!=0 || descriptor.back()!='\n')return false;
    for(unsigned char c:descriptor)if(c!=10 && (c<32 || c>126))return false;
    return sha(descriptor)==hash;
}
}
