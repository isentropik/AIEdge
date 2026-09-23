#pragma once
#include "ImageArchiveConfig.h"
#include "ImageArchiveTransport.h"

namespace ImageArchive {
inline bool validArchiveSettingsEncoding(const std::string& body) {
    if(body.empty()||body.size()>12288)return false;
    // Only newline escapes are needed for a PEM. Reject NUL, Unicode aliases,
    // escaped field names and hidden trailing string content before cJSON decoding.
    for(size_t i=0;i<body.size();++i){
        const unsigned char c=body[i];
        if(c==0||c>127)return false;
        if(c=='\\'){
            if(++i>=body.size()||(body[i]!='n'&&body[i]!='r'))return false;
        }
    }
    return true;
}
// A single document keeps destination, trust and authorization in one revision.
// Persistence must still use a verified journaled transaction; this parser writes nothing.
inline bool parseArchiveSettings(const std::string& body,StartupConfig& out,Destination& target) {
    out=StartupConfig{};target=Destination{};
    if(!validArchiveSettingsEncoding(body))return false;
    cJSON* json=cJSON_ParseWithLengthOpts(body.c_str(),body.size()+1,nullptr,1);
    if(!json)return false;
    struct Cleanup{cJSON* p;~Cleanup(){cJSON_Delete(p);}} cleanup{json};
    if(!cJSON_IsObject(json))return false;
    const char* names[]={"version","config","token","ca_pem"};
    cJSON* fields[4]={};
    for(auto* item=json->child;item;item=item->next){
        int found=-1;
        if(!item->string)return false;
        for(int i=0;i<4;++i)if(std::strcmp(item->string,names[i])==0)found=i;
        if(found<0||fields[found])return false;
        fields[found]=item;
    }
    if(!cJSON_IsNumber(fields[0])||fields[0]->valuedouble!=1||!cJSON_IsObject(fields[1]))return false;
    char* encoded=cJSON_PrintUnformatted(fields[1]);
    if(!encoded)return false;
    StartupConfig config;const bool valid=parseStartupConfig(encoded,config);cJSON_free(encoded);
    if(!valid)return false;
    Destination destination;
    if(config.enabled||fields[2]||fields[3]){
        if(!cJSON_IsString(fields[2])||!cJSON_IsString(fields[3]))return false;
        destination.host=config.host;destination.port=config.port;destination.timeoutMs=config.timeoutMs;
        destination.token=fields[2]->valuestring;destination.certificatePem=fields[3]->valuestring;
        if(!validArchiveDestination(destination)||!validName(config.device))return false;
    }
    out=config;target=destination;return true;
}
}
