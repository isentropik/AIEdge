#pragma once
#include "ImageArchiveMetadata.h"
#include "cJSON.h"
#include <cstring>

namespace ImageArchive {
// Destination folder belongs to the receiver; it is never accepted from a
// meter request. Credentials and trust anchor are loaded separately at startup.
struct StartupConfig {
    bool enabled=false;
    std::string host,device;
    unsigned port=8766,timeoutMs=15000;
};
inline bool parseStartupConfig(const std::string& body,StartupConfig& out) {
    out=StartupConfig{};
    if(body.empty()||body.size()>1024)return false;
    // Restrict this small machine-written configuration to literal ASCII.
    // Reject escaped NULs and names that would compare equal after decoding.
    for(unsigned char c:body)if(c==0||c=='\\'||c>127)return false;
    cJSON* json=cJSON_ParseWithLengthOpts(body.c_str(),body.size()+1,nullptr,1);
    if(!json)return false;
    struct Cleanup{cJSON* p;~Cleanup(){cJSON_Delete(p);}} cleanup{json};
    if(!cJSON_IsObject(json))return false;
    const char* names[]={"enabled","host","device_id","port","timeout_ms"};
    cJSON* fields[5]={};
    for(auto* child=json->child;child;child=child->next){
        int index=-1;
        if(!child->string)return false;
        for(int i=0;i<5;++i)if(std::strcmp(child->string,names[i])==0)index=i;
        if(index<0||fields[index])return false;
        fields[index]=child;
    }
    if(!fields[0]||!cJSON_IsBool(fields[0]))return false;
    StartupConfig config;config.enabled=cJSON_IsTrue(fields[0]);
    if(fields[1]){
        if(!cJSON_IsString(fields[1])||!fields[1]->valuestring)return false;
        config.host=fields[1]->valuestring;
        auto alnum=[](char c){return (c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9');};
        if(config.host.empty()||config.host.size()>253||!alnum(config.host.front())||!alnum(config.host.back()))return false;
        for(char c:config.host)if(!alnum(c)&&c!='.'&&c!='-')return false;
    }
    if(fields[2]){
        if(!cJSON_IsString(fields[2])||!fields[2]->valuestring)return false;
        config.device=fields[2]->valuestring;
        if(!validName(config.device))return false;
    }
    for(int i=3;i<5;++i)if(fields[i]){
        const double value=fields[i]->valuedouble;
        const unsigned low=i==3?1:1000,high=i==3?65535:30000;
        if(!cJSON_IsNumber(fields[i])||!(value>=low&&value<=high)||value!=static_cast<unsigned>(value))return false;
        if(i==3)config.port=static_cast<unsigned>(value);else config.timeoutMs=static_cast<unsigned>(value);
    }
    if(config.enabled&&(config.host.empty()||config.device.empty()))return false;
    out=config;return true;
}
}
