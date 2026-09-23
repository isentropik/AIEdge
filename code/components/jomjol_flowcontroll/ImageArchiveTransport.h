#pragma once
#include "ImageUploadQueue.h"

namespace ImageArchive {
struct Destination {
    std::string host, certificatePem, token;
    unsigned port=8766;
    unsigned timeoutMs=15000;
};
struct UploadAttempt {
    int status=0;
    Receipt receipt;
    const char* error="not_started";
};
inline bool validArchiveDestination(const Destination& d) {
    if(d.host.empty() || d.host.size()>253 || d.port==0 || d.port>65535 ||
       d.timeoutMs<1000 || d.timeoutMs>30000 || d.token.size()<32 || d.token.size()>256 ||
       d.certificatePem.empty() || d.certificatePem.size()>8192 || d.certificatePem.find('\0')!=std::string::npos) return false;
    auto alnum=[](char c){return (c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9');};
    if(!alnum(d.host.front())||!alnum(d.host.back())) return false;
    for(char c:d.host)if(!alnum(c)&&c!='.'&&c!='-')return false;
    for(char c:d.token)if(!alnum(c)&&c!='_'&&c!='-')return false;
    return true;
}
// Caller owns the spool exclusively for this attempt. No capture or deletion.
UploadAttempt uploadSpool(const std::string& root,const Ticket& ticket,const Destination& destination);
}
