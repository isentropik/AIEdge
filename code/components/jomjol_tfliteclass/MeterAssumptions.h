#pragma once
#include "MeterAccounting.h"
#include "cJSON.h"
#include <cstring>
#include <string>
namespace meter {
// Optional physical upper bound, never a guessed or learned household rate.
struct Assumptions {
    bool hasMaximumFlow = false;
    double maximumFlowFt3Hour = 0;
};
inline bool validAssumptions(const Assumptions& a) {
    if (!a.hasMaximumFlow) return a.maximumFlowFt3Hour == 0;
    const double perSecond=a.maximumFlowFt3Hour/3600.0;
    return std::isfinite(a.maximumFlowFt3Hour) && a.maximumFlowFt3Hour>0 &&
        std::isfinite(perSecond) && perSecond>0;
}
inline bool assumptionBounds(const Assumptions& a, Bounds& output) {
    if (!validAssumptions(a)) return false;
    Bounds next;
    next.hasMaximumRate=a.hasMaximumFlow;
    next.maximumRateFt3S=a.hasMaximumFlow?a.maximumFlowFt3Hour/3600.0:0;
    output=next;return true;
}
// A rate change must not reuse a reference or cumulative segment with other bounds.
// Disabled retains the established namespace. Enabled names encode the effective
// IEEE-754 rate exactly, independent of locale and host byte order.
inline bool assumptionNamespace(const Assumptions& a, std::string& output) {
    Bounds bounds;if(!assumptionBounds(a,bounds))return false;
    std::string next="polar-meter-reference";
    if(a.hasMaximumFlow) {
        static_assert(sizeof(double)==sizeof(uint64_t),"64-bit double required");
        static_assert(std::numeric_limits<double>::is_iec559,"IEEE double required");
        uint64_t bits=0;std::memcpy(&bits,&bounds.maximumRateFt3S,sizeof(bits));
        next+="-rate-v1-";
        const char* hex="0123456789abcdef";
        for(int shift=60;shift>=0;shift-=4)next+=hex[(bits>>shift)&15];
    }
    output=next;return true;
}
inline bool parseAssumptions(const std::string& bytes, Assumptions& output) {
    if(bytes.empty()||bytes.size()>512||bytes.find('\0')!=std::string::npos||bytes.find('\\')!=std::string::npos)return false;
    cJSON* root=cJSON_ParseWithLengthOpts(bytes.c_str(),bytes.size()+1,nullptr,1);
    if(!root)return false;
    struct Cleanup{cJSON* p;~Cleanup(){cJSON_Delete(p);}} cleanup{root};
    if(!cJSON_IsObject(root))return false;
    cJSON *version=nullptr,*flow=nullptr;
    for(auto* c=root->child;c;c=c->next) {
        if(c->string&&!std::strcmp(c->string,"version")&&!version)version=c;
        else if(c->string&&!std::strcmp(c->string,"maximum_flow_ft3_hour")&&!flow)flow=c;
        else return false;
    }
    if(!cJSON_IsNumber(version)||version->valuedouble!=1||!flow)return false;
    Assumptions next;
    if(cJSON_IsNumber(flow)){next.hasMaximumFlow=true;next.maximumFlowFt3Hour=flow->valuedouble;}
    else if(!cJSON_IsNull(flow))return false;
    if(!validAssumptions(next))return false;
    output=next;return true;
}
}
