#pragma once
#include "ImageUploadQueue.h"
#include <cstring>

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
// Only stable internal codes reach status JSON; never copy transport text,
// response bodies, server addresses or credentials into diagnostics.
inline const char* uploadErrorCode(const char* error) {
    if(!error)return "none";
    const char* const codes[]={
        "none","not_started","upload_failed","queue_transition_failed",
        "settings_client_failed","settings_headers_failed","settings_connection_failed",
        "settings_timeout","settings_write_failed","settings_response_failed",
        "settings_rejected","settings_response_timeout","settings_response_read_failed",
        "settings_receipt_too_large","settings_response_incomplete","settings_receipt_invalid",
        "invalid_destination_or_identity","spool_verification_failed","settings_file_invalid_or_missing",
        "metadata_encoding_failed","client_init_failed","request_headers_failed","spool_open_failed",
        "spool_seek_failed","connection_failed","spool_read_failed","upload_timeout","upload_write_failed",
        "spool_changed_or_close_failed","response_headers_failed","server_rejected","response_timeout",
        "response_read_failed","receipt_too_large","response_incomplete","receipt_invalid"
    };
    for(const char* code:codes)if(std::strcmp(error,code)==0)return code;
    return "upload_failed";
}
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
