#pragma once
#include "ImageArchiveConfigFile.h"

namespace ImageArchive {
struct SettingsSnapshot {
    bool existed=false;
    std::string before,revision;
    StartupConfig config;
    Destination destination;
};
// Caller holds processing/storage guards. Inspection never repairs or writes.
template<class Hash>
bool inspectArchiveSettings(const std::string& directory,SettingsSnapshot& out){
    out=SettingsSnapshot{};SettingsSnapshot next;std::string body;
    auto read=readArchiveConfigFile(directory+"/image-archive-settings.json.journal",65536,body);
    if(read!=SmallFile::Missing)return false; // Boot/save recovery must finish first.
    read=readArchiveConfigFile(directory+"/image-archive-settings.json",12288,body);
    Hash hash;
    auto add=[&](const std::string& value){
        const auto length=std::to_string(value.size())+":";
        return hash.update(reinterpret_cast<const unsigned char*>(length.data()),length.size())&&
            hash.update(reinterpret_cast<const unsigned char*>(value.data()),value.size());
    };
    if(read==SmallFile::Ok){
        next.existed=true;next.before=body;
        if(!parseArchiveSettings(body,next.config,next.destination)||!add("unified")||!add(body))return false;
    }else if(read==SmallFile::Missing){
        if(!add("legacy"))return false;
        const char* files[]={"image-archive.json","image-archive-ca.pem","image-archive-token.txt"};
        const size_t limits[]={1024,8192,258};std::string values[3];bool present[3]={};
        for(int i=0;i<3;++i){
            read=readArchiveConfigFile(directory+"/"+files[i],limits[i],values[i]);
            if(read!=SmallFile::Missing&&read!=SmallFile::Ok)return false;
            present[i]=read==SmallFile::Ok;
            if(!add(present[i]?"present":"missing")||!add(values[i]))return false;
        }
        if(present[0]&&!parseStartupConfig(values[0],next.config))return false;
        if(next.config.enabled){
            auto& d=next.destination;d.host=next.config.host;d.port=next.config.port;d.timeoutMs=next.config.timeoutMs;
            d.certificatePem=values[1];d.token=values[2];
            if(!d.token.empty()&&d.token.back()=='\n'){d.token.pop_back();if(!d.token.empty()&&d.token.back()=='\r')d.token.pop_back();}
            if(!validArchiveDestination(d))return false;
        }
    }else return false;
    next.revision=hash.finish();if(next.revision.size()!=64)return false;
    out=next;return true;
}
// null credentials explicitly retain the saved values. They are never returned
// to the browser. Revalidation after replacement rejects invalid combinations.
inline bool prepareArchiveSettings(const std::string& request,const SettingsSnapshot& saved,std::string& result){
    result.clear();if(!validArchiveSettingsEncoding(request))return false;
    cJSON* json=cJSON_ParseWithLengthOpts(request.c_str(),request.size()+1,nullptr,1);
    if(!json)return false;
    struct Cleanup{cJSON* p;~Cleanup(){cJSON_Delete(p);}} cleanup{json};
    if(!cJSON_IsObject(json))return false;
    const char* names[]={"version","config","token","ca_pem"};bool seen[4]={};
    for(auto* child=json->child;child;child=child->next){
        int index=-1;if(!child->string)return false;
        for(int i=0;i<4;++i)if(std::strcmp(names[i],child->string)==0)index=i;
        if(index<0||seen[index])return false;
        seen[index]=true;
    }
    for(int i=2;i<4;++i){
        auto* field=cJSON_GetObjectItemCaseSensitive(json,names[i]);
        if(cJSON_IsNull(field)){
            const auto& value=i==2?saved.destination.token:saved.destination.certificatePem;
            if(value.empty()){cJSON_DeleteItemFromObjectCaseSensitive(json,names[i]);}
            else {
                auto* replacement=cJSON_CreateString(value.c_str());
                if(!replacement)return false;
                if(!cJSON_ReplaceItemInObjectCaseSensitive(json,names[i],replacement)){cJSON_Delete(replacement);return false;}
            }
        }
    }
    char* bytes=cJSON_PrintUnformatted(json);if(!bytes)return false;
    std::string candidate=bytes;cJSON_free(bytes);StartupConfig config;Destination destination;
    if(!parseArchiveSettings(candidate,config,destination))return false;
    result=std::move(candidate);return true;
}
}
