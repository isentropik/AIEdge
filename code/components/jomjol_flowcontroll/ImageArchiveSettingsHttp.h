#pragma once
#include "ImageArchiveSettingsEditor.h"
#include "ImageArchiveSha.h"
#include "ProcessingAccess.h"
#include "../jomjol_fileserver_ota/UpdateAccess.h"
#include "esp_http_server.h"
#include "esp_timer.h"

namespace ImageArchive {
inline esp_err_t settingsReply(httpd_req_t* req,const char* status,const char* message){
    httpd_resp_set_status(req,status);httpd_resp_set_type(req,"application/json");
    httpd_resp_set_hdr(req,"Cache-Control","no-store");
    return httpd_resp_sendstr(req,message);
}
inline esp_err_t handleArchiveSettings(httpd_req_t* req,const std::string& directory){
    if(httpd_req_get_url_query_len(req))return settingsReply(req,"400 Bad Request","{\"error\":\"query_not_supported\"}");
    const bool save=req->method==HTTP_POST;
    if(!save&&req->method!=HTTP_GET)return settingsReply(req,"405 Method Not Allowed","{\"error\":\"method_not_supported\"}");
    std::string body,expected;
    if(save){
        char type[40]={},revision[70]={};
        // JSON plus a custom revision header requires a browser preflight across
        // origins. This route exposes no CORS permission or OPTIONS handler.
        if(httpd_req_get_hdr_value_str(req,"Content-Type",type,sizeof(type))!=ESP_OK||std::strcmp(type,"application/json")||
           httpd_req_get_hdr_value_str(req,"X-AIEdge-Revision",revision,sizeof(revision))!=ESP_OK||!validHash(revision))
            return settingsReply(req,"400 Bad Request","{\"error\":\"json_and_revision_required\"}");
        if(req->content_len<=0||req->content_len>12288)return settingsReply(req,"413 Payload Too Large","{\"error\":\"invalid_body_size\"}");
        expected=revision;body.resize(req->content_len);size_t got=0;const auto start=esp_timer_get_time();
        while(got<body.size()){
            if(esp_timer_get_time()-start>8000000)return settingsReply(req,"408 Request Timeout","{\"error\":\"body_timeout\"}");
            const int count=httpd_req_recv(req,&body[got],body.size()-got);
            if(count<=0)return settingsReply(req,"400 Bad Request","{\"error\":\"incomplete_body\"}");
            got+=static_cast<size_t>(count);
        }
    }else if(req->content_len)return settingsReply(req,"400 Bad Request","{\"error\":\"unexpected_body\"}");
    ProcessingAccess processing;if(!processing)return settingsReply(req,"409 Conflict","{\"error\":\"processing_busy\"}");
    UpdateAccess update;if(!update)return settingsReply(req,"409 Conflict","{\"error\":\"storage_busy\"}");
    SettingsSnapshot saved;
    if(!inspectArchiveSettings<Sha256>(directory,saved))return settingsReply(req,"503 Service Unavailable","{\"error\":\"settings_unavailable_or_recovery_required\"}");
    if(save){
        if(expected!=saved.revision)return settingsReply(req,"409 Conflict","{\"error\":\"settings_changed_reload_before_saving\"}");
        std::string next;if(!prepareArchiveSettings(body,saved,next))return settingsReply(req,"400 Bad Request","{\"error\":\"invalid_archive_settings\"}");
        ConfigStorage::Files disk;
        const auto result=SettingsStore::commit(disk,directory+"/image-archive-settings.json",saved.existed,saved.before,next);
        if(result==ConfigJournal::Result::CleanupPending)return settingsReply(req,"503 Service Unavailable","{\"error\":\"saved_but_recovery_required\"}");
        if(result!=ConfigJournal::Result::Ok)return settingsReply(req,"503 Service Unavailable","{\"error\":\"save_unconfirmed_do_not_retry\"}");
        return settingsReply(req,"200 OK","{\"status\":\"saved_restart_required\",\"active_changed\":false}");
    }
    // Host and device names were restricted to safe ASCII by the shared parser.
    const auto& c=saved.config;
    const std::string json="{\"version\":1,\"revision\":\""+saved.revision+"\",\"enabled\":"+(c.enabled?"true":"false")+
        ",\"host\":\""+c.host+"\",\"device_id\":\""+c.device+"\",\"port\":"+std::to_string(c.port)+
        ",\"timeout_ms\":"+std::to_string(c.timeoutMs)+",\"has_token\":"+(saved.destination.token.empty()?"false":"true")+
        ",\"has_certificate\":"+(saved.destination.certificatePem.empty()?"false":"true")+"}";
    return settingsReply(req,"200 OK",json.c_str());
}
inline esp_err_t archiveSettingsHttp(httpd_req_t* req){return handleArchiveSettings(req,"/sdcard/config");}
}
