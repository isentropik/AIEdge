#pragma once
#include "MeterAccountingController.h"
#include "MeterStatus.h"
#include "ImageArchiveSettingsHttp.h"
namespace meter {
template<class Changed>
inline esp_err_t handleAssumptionsSettings(httpd_req_t* req,const std::string& directory,
                                          AccountingController& controller,Changed changed){
 using ImageArchive::settingsReply;
 if(httpd_req_get_url_query_len(req))return settingsReply(req,"400 Bad Request",R"({"error":"query_not_supported"})");
 const bool save=req->method==HTTP_POST;
 if(!save&&req->method!=HTTP_GET)return settingsReply(req,"405 Method Not Allowed",R"({"error":"method_not_supported"})");
 std::string body,expected;
 if(save){
  char type[40]={},revision[70]={};
  if(httpd_req_get_hdr_value_str(req,"Content-Type",type,sizeof(type))!=ESP_OK||std::strcmp(type,"application/json")||
     httpd_req_get_hdr_value_str(req,"X-AIEdge-Revision",revision,sizeof(revision))!=ESP_OK||!ImageArchive::validHash(revision))
   return settingsReply(req,"400 Bad Request",R"({"error":"json_and_revision_required"})");
  if(req->content_len<=0||req->content_len>512)return settingsReply(req,"413 Payload Too Large",R"({"error":"invalid_body_size"})");
  expected=revision;body.resize(req->content_len);size_t got=0;const auto start=esp_timer_get_time();
  while(got<body.size()){
   if(esp_timer_get_time()-start>8000000)return settingsReply(req,"408 Request Timeout",R"({"error":"body_timeout"})");
   const int n=httpd_req_recv(req,&body[got],body.size()-got);
   if(n<=0) {
    return settingsReply(req,"400 Bad Request",R"({"error":"incomplete_body"})");
   }
   got+=static_cast<size_t>(n);
  }
 }else if(req->content_len)return settingsReply(req,"400 Bad Request",R"({"error":"unexpected_body"})");
 ProcessingAccess processing;if(!processing)return settingsReply(req,"409 Conflict",R"({"error":"processing_busy"})");
 UpdateAccess update;if(!update)return settingsReply(req,"409 Conflict",R"({"error":"storage_busy"})");
 ConfigStorage::Files disk;AssumptionsStore::Snapshot saved;
 const std::string path=directory+"/meter-assumptions.json";
 if(AssumptionsStore::inspect(disk,path,saved)!=ConfigJournal::Result::Ok)
  return settingsReply(req,"503 Service Unavailable",R"({"error":"settings_unavailable_or_recovery_required"})");
 ImageArchive::Sha256 hash;
 const std::string tagged=(saved.existed?"assumptions-v1:":"missing-assumptions-v1:")+saved.bytes;
 if(!hash.update(reinterpret_cast<const unsigned char*>(tagged.data()),tagged.size()))
  return settingsReply(req,"503 Service Unavailable",R"({"error":"revision_unavailable"})");
 const auto revision=hash.finish();
 if(revision.size()!=64)return settingsReply(req,"503 Service Unavailable",R"({"error":"revision_unavailable"})");
 if(save){
  if(expected!=revision)return settingsReply(req,"409 Conflict",R"({"error":"settings_changed_reload_before_saving"})");
  Assumptions next;if(!parseAssumptions(body,next))return settingsReply(req,"400 Bad Request",R"({"error":"invalid_flow_limit"})");
  const auto result=AssumptionsStore::commit(disk,path,saved.existed,saved.bytes,body);
  if(result!=ConfigJournal::Result::Ok)return settingsReply(req,"503 Service Unavailable",R"({"error":"save_unconfirmed_reload_before_retry"})");
  const bool active=controller.apply(disk,next);
  changed(); // Publish and invalidate history while both guards remain held.
  return settingsReply(req,"200 OK",active?R"({"status":"saved_and_active","active":true})":R"({"status":"saved_not_active","active":false})");
 }
 std::string desired;assumptionNamespace(saved.value,desired);
 const auto current=controller.current();
 const bool active=controller.active(),matches=active&&controller.activeNamespace()==desired;
 const std::string settings=saved.existed?saved.bytes:R"({"version":1,"maximum_flow_ft3_hour":null})";
 const std::string json="{\"revision\":\""+revision+"\",\"settings\":"+settings+
  ",\"initialized\":"+(active?"true":"false")+",\"saved_active\":"+(matches?"true":"false")+
  ",\"active_maximum_flow_ft3_hour\":"+(active&&current.assumptions.hasMaximumRate?jsonNumber(current.assumptions.maximumRateFt3S*3600):"null")+"}";
 return settingsReply(req,"200 OK",json.c_str());
}
}
