#pragma once
#include "../jomjol_tfliteclass/MeterProfileEditor.h"
#include "ImageArchiveSettingsHttp.h"
namespace meter {
inline esp_err_t handleProfileSettings(httpd_req_t* req,const std::string& directory){
 using ImageArchive::settingsReply;
 if(httpd_req_get_url_query_len(req))return settingsReply(req,"400 Bad Request","{\"error\":\"query_not_supported\"}");
 const bool save=req->method==HTTP_POST;
 if(!save&&req->method!=HTTP_GET)return settingsReply(req,"405 Method Not Allowed","{\"error\":\"method_not_supported\"}");
 std::string body,expected;
 if(save){
  char type[40]={},revision[70]={};
  if(httpd_req_get_hdr_value_str(req,"Content-Type",type,sizeof(type))!=ESP_OK||std::strcmp(type,"application/json")||
     httpd_req_get_hdr_value_str(req,"X-AIEdge-Revision",revision,sizeof(revision))!=ESP_OK||!ImageArchive::validHash(revision))
   return settingsReply(req,"400 Bad Request","{\"error\":\"json_and_revision_required\"}");
  if(req->content_len<=0||req->content_len>2048)return settingsReply(req,"413 Payload Too Large","{\"error\":\"invalid_body_size\"}");
  expected=revision;body.resize(req->content_len);size_t got=0;const auto start=esp_timer_get_time();
  while(got<body.size()){
   if(esp_timer_get_time()-start>8000000)return settingsReply(req,"408 Request Timeout","{\"error\":\"body_timeout\"}");
   const int n=httpd_req_recv(req,&body[got],body.size()-got);if(n<=0)return settingsReply(req,"400 Bad Request","{\"error\":\"incomplete_body\"}");got+=n;
  }
 }else if(req->content_len)return settingsReply(req,"400 Bad Request","{\"error\":\"unexpected_body\"}");
 ProcessingAccess processing;if(!processing)return settingsReply(req,"409 Conflict","{\"error\":\"processing_busy\"}");
 UpdateAccess update;if(!update)return settingsReply(req,"409 Conflict","{\"error\":\"storage_busy\"}");
 ConfigStorage::Files disk;ProfileSnapshot saved;const std::string path=directory+"/meter-profile.json";
 if(!inspectProfile<ImageArchive::Sha256>(disk,path,saved))return settingsReply(req,"503 Service Unavailable","{\"error\":\"profile_unavailable_or_recovery_required\"}");
 if(save){
  if(expected!=saved.revision)return settingsReply(req,"409 Conflict","{\"error\":\"profile_changed_reload_before_saving\"}");
  RegisterProfile next;if(!parseProfile(body,next))return settingsReply(req,"400 Bad Request","{\"error\":\"invalid_profile\"}");
  if(saved.existed&&!samePhysicalScale(saved.profile,next))return settingsReply(req,"409 Conflict","{\"error\":\"physical_scale_change_requires_history_migration\"}");
  auto result=ProfileStore::commit(disk,path,saved.existed,saved.bytes,body);
  if(result!=ConfigJournal::Result::Ok)return settingsReply(req,"503 Service Unavailable","{\"error\":\"save_unconfirmed_reload_before_retry\"}");
  // Saving metadata is not activation of a different recognition/accounting model.
  return settingsReply(req,"200 OK","{\"status\":\"saved_not_active\",\"active_changed\":false}");
 }
 const std::string json="{\"revision\":\""+saved.revision+"\",\"profile\":"+(saved.existed?saved.bytes:"null")+
  ",\"model_compatible\":"+(saved.existed&&matchesFrozenGasScale(saved.profile)?"true":"false")+",\"activation\":\"not_integrated\"}";
 return settingsReply(req,"200 OK",json.c_str());
}
inline esp_err_t profileSettingsHttp(httpd_req_t* req){return handleProfileSettings(req,"/sdcard/config");}

}
