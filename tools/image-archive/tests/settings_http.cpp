
#include "ImageArchiveSettingsHttp.h"
#include <cassert>
#include <iostream>
int64_t fake_time=0;
using namespace ImageArchive;
std::string field(const std::string& data,const char* name){auto* json=cJSON_Parse(data.c_str());assert(json);auto* value=cJSON_GetObjectItem(json,name);assert(cJSON_IsString(value));std::string result=value->valuestring;cJSON_Delete(json);return result;}
int main(int argc,char** argv){assert(argc==2);const std::string root=argv[1],path=root+"/image-archive-settings.json";
 ConfigStorage::Files disk;
 auto call=[&](httpd_req_t& request){assert(handleArchiveSettings(&request,root)==ESP_OK);assert(request.responseHeaders["Cache-Control"]=="no-store");assert(!request.responseHeaders.count("Access-Control-Allow-Origin"));};
 httpd_req_t get;call(get);assert(get.status=="200 OK");const auto revision=field(get.output,"revision");
 const std::string token(32,'a'),pem="-----BEGIN CERTIFICATE-----\nfixture\n-----END CERTIFICATE-----\n";
 const std::string enabled=R"({"version":1,"config":{"enabled":true,"host":"nas.local","device_id":"meter"},"token":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","ca_pem":"-----BEGIN CERTIFICATE-----\nfixture\n-----END CERTIFICATE-----\n"})";
 auto post=[&](const std::string& body,const std::string& version){httpd_req_t r;r.method=HTTP_POST;r.input=body;r.content_len=body.size();r.headers["Content-Type"]="application/json";r.headers["X-AIEdge-Revision"]=version;return r;};
 auto checkError=[&](httpd_req_t r,const char* status){std::string before;const auto old=disk.read(path,before);call(r);assert(r.status==status);std::string after;assert(disk.read(path,after)==old&&before==after);};
 checkError(post(enabled,"bad"),"400 Bad Request");
 auto missing=post(enabled,revision);missing.headers.erase("Content-Type");checkError(missing,"400 Bad Request");
 auto incomplete=post(enabled,revision);incomplete.failAfter=13;checkError(incomplete,"400 Bad Request");
 auto huge=post(enabled,revision);huge.content_len=12289;checkError(huge,"413 Payload Too Large");
 checkError(post("{}",revision),"400 Bad Request");
 {ProcessingAccess busy;checkError(post(enabled,revision),"409 Conflict");}
 {UpdateAccess busy;checkError(post(enabled,revision),"409 Conflict");}
 auto save=post(enabled,revision);call(save);assert(save.status=="200 OK");assert(save.output.find("saved_restart_required")!=std::string::npos);
 std::string stored;assert(disk.read(path,stored)==ConfigJournal::Read::Ok);StartupConfig config;Destination dest;assert(parseArchiveSettings(stored,config,dest));assert(dest.token==token&&dest.certificatePem==pem);
 httpd_req_t read;call(read);assert(read.status=="200 OK");assert(read.output.find(token)==std::string::npos&&read.output.find("BEGIN CERTIFICATE")==std::string::npos);
 const auto updated=field(read.output,"revision");assert(updated!=revision);
 checkError(post(enabled,revision),"409 Conflict");
 const std::string retained=R"({"version":1,"config":{"enabled":false,"host":"nas.local","device_id":"meter"},"token":null,"ca_pem":null})";
 auto disable=post(retained,updated);call(disable);assert(disable.status=="200 OK");
 assert(disk.read(path,stored)==ConfigJournal::Read::Ok&&parseArchiveSettings(stored,config,dest));assert(!config.enabled&&dest.token==token&&dest.certificatePem==pem);
 SettingsSnapshot snap;assert(inspectArchiveSettings<Sha256>(root,snap));std::string output;
 for(auto invalid:{R"({"version":1,"version":1,"config":{"enabled":false}})",R"({"version":1,"config":{"enabled":false},"extra":true})",R"({"version":1,"config":{"enabled":false},"token":"a\u0000b"})"})assert(!prepareArchiveSettings(invalid,snap,output));
 auto query=httpd_req_t{};query.query=1;checkError(query,"400 Bad Request");
 assert(disk.writeSync(path+".journal","broken"));httpd_req_t damaged;call(damaged);assert(damaged.status=="503 Service Unavailable");assert(disk.remove(path+".journal"));
 assert(disk.remove(path));
 assert(disk.writeSync(root+"/image-archive.json",R"({"enabled":true,"host":"nas.local","device_id":"meter"})"));
 assert(disk.writeSync(root+"/image-archive-token.txt",token+"\r\n"));assert(disk.writeSync(root+"/image-archive-ca.pem",pem));
 SettingsSnapshot legacy;assert(inspectArchiveSettings<Sha256>(root,legacy));assert(!legacy.existed&&legacy.destination.token==token);
 assert(disk.writeSync(root+"/image-archive-token.txt",std::string(32,'b')));SettingsSnapshot changed;assert(inspectArchiveSettings<Sha256>(root,changed));assert(changed.revision!=legacy.revision);
 auto migrate=post(retained,changed.revision);call(migrate);assert(migrate.status=="200 OK");assert(disk.read(path,stored)==ConfigJournal::Read::Ok&&parseArchiveSettings(stored,config,dest));assert(dest.token==std::string(32,'b'));
 std::cout<<"Settings HTTP/editor tests passed: bounded partial requests, guard contention, credential retention/redaction, stale edits, legacy migration and damaged-journal refusal\n";
}
