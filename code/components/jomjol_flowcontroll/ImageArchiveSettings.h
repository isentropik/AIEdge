#pragma once
#include "ImageSettingsDescriptor.h"
#include "cJSON.h"
#include <cstring>

namespace ImageArchive {
inline bool settingsReceiptMatches(const std::string& body,const std::string& expectedHash) {
    if(!validHash(expectedHash) || body.empty() || body.size()>512)return false;
    for(unsigned char c:body)if(c==0 || c=='\\' || c>127)return false;
    cJSON* json=cJSON_ParseWithLengthOpts(body.c_str(),body.size()+1,nullptr,1);
    if(!json)return false;
    struct Cleanup{cJSON* p;~Cleanup(){cJSON_Delete(p);}} cleanup{json};
    if(!cJSON_IsObject(json))return false;
    const char* names[]={"version","settings_sha256","verified_readback","duplicate"};
    cJSON* fields[4]={};
    for(auto* child=json->child;child;child=child->next) {
        int index=-1;
        if(!child->string)return false;
        for(int i=0;i<4;++i)if(std::strcmp(child->string,names[i])==0)index=i;
        if(index<0 || fields[index])return false;
        fields[index]=child;
    }
    for(auto* field:fields)if(!field)return false;
    return cJSON_IsNumber(fields[0]) && fields[0]->valuedouble==1 &&
        cJSON_IsString(fields[1]) && fields[1]->valuestring && expectedHash==fields[1]->valuestring &&
        cJSON_IsTrue(fields[2]) && cJSON_IsBool(fields[3]);
}
}
