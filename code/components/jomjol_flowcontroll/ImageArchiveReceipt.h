#pragma once
#include "ImageUploadQueue.h"
#include "cJSON.h"
#include <cstring>

namespace ImageArchive {
// The receiver emits a flat ASCII object. Bound allocation and reject duplicate
// keys, hidden NUL suffixes, escaped aliases and trailing content explicitly.
inline bool parseReceipt(const std::string& body, Receipt& out) {
    out=Receipt{};
    if(body.empty() || body.size()>1024) return false;
    for(unsigned char c:body) if(c==0 || c=='\\' || c>127) return false;
    cJSON* json=cJSON_ParseWithLengthOpts(body.c_str(),body.size()+1,nullptr,1);
    if(!json) return false;
    struct Cleanup {cJSON* p;~Cleanup(){cJSON_Delete(p);}} cleanup{json};
    if(!cJSON_IsObject(json)) return false;
    const char* names[]={"version","capture_id","image_sha256","record_sha256",
        "duplicate","verified_readback","review_status","training_eligible"};
    cJSON* fields[8]={};
    for(auto* child=json->child;child;child=child->next) {
        if(!child->string) return false;
        int index=-1;
        for(int i=0;i<8;++i) if(std::strcmp(child->string,names[i])==0) index=i;
        if(index<0 || fields[index]) return false;
        fields[index]=child;
    }
    for(auto* field:fields) if(!field) return false;
    if(!cJSON_IsNumber(fields[0]) || fields[0]->valuedouble!=1 ||
       !cJSON_IsBool(fields[4]) || !cJSON_IsTrue(fields[5]) || !cJSON_IsFalse(fields[7])) return false;
    for(int i:{1,2,3,6}) if(!cJSON_IsString(fields[i]) || !fields[i]->valuestring) return false;
    Receipt r;r.version=1;r.capture=fields[1]->valuestring;r.image=fields[2]->valuestring;
    r.record=fields[3]->valuestring;r.reviewStatus=fields[6]->valuestring;
    r.verifiedReadback=true;r.trainingEligible=false;
    if(!validHash(r.capture)||!validHash(r.image)||!validHash(r.record)||r.reviewStatus!="unreviewed") return false;
    out=r;
    return true;
}
} // namespace ImageArchive
