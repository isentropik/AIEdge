#include "MeterProfileSettingsHttp.h"
#include <cassert>
#include <iostream>
int64_t fake_time=0;
std::string field(const std::string&body,const char*key){auto*j=cJSON_Parse(body.c_str());assert(j);auto*v=cJSON_GetObjectItem(j,key);assert(cJSON_IsString(v));std::string result=v->valuestring;cJSON_Delete(j);return result;}
int main(int argc,char**argv){assert(argc==2);std::string directory=argv[1];ConfigStorage::Files disk;
 auto call=[&](httpd_req_t&r){assert(meter::handleProfileSettings(&r,directory)==ESP_OK);assert(r.responseHeaders["Cache-Control"]=="no-store");assert(!r.responseHeaders.count("Access-Control-Allow-Origin"));};
 httpd_req_t get;call(get);assert(get.status=="200 OK"&&get.output.find("\"profile\":null")!=std::string::npos);auto revision=field(get.output,"revision");
 const std::string body=R"({"version":1,"kind":"gas","source_unit":"ft3","display_unit":"ft3","units_per_count":1,"has_secondary":true,"secondary_units_per_revolution":5,"confirmed":true})";
 auto post=[&](std::string bytes,std::string rev){httpd_req_t r;r.method=HTTP_POST;r.input=bytes;r.content_len=bytes.size();r.headers["Content-Type"]="application/json";r.headers["X-AIEdge-Revision"]=rev;return r;};
 auto save=post(body,revision);call(save);assert(save.status=="200 OK"&&save.output.find("saved_display_only")!=std::string::npos);
 assert(meter::activeDisplayUnit()==meter::RegisterUnit::CubicFoot);
 std::string stored;assert(disk.read(directory+"/meter-profile.json",stored)==ConfigJournal::Read::Ok&&stored==body);
 auto stale=post(body,revision);call(stale);assert(stale.status=="409 Conflict");
 httpd_req_t reread;call(reread);revision=field(reread.output,"revision");assert(reread.output.find("\"model_compatible\":true")!=std::string::npos);
 auto bad=post(body,revision);bad.headers.erase("X-AIEdge-Revision");call(bad);assert(bad.status=="400 Bad Request");
 bad=post(body,revision);bad.failAfter=0;call(bad);assert(bad.status=="400 Bad Request");
 bad=post(body,revision);bad.content_len=2049;call(bad);assert(bad.status=="413 Payload Too Large");
 bad=post(body,revision);bad.method=99;call(bad);assert(bad.status=="405 Method Not Allowed");
 bad=post(body,revision);bad.query=1;call(bad);assert(bad.status=="400 Bad Request");
 {ProcessingAccess lock;auto r=post(body,revision);call(r);assert(r.status=="409 Conflict");}
 {UpdateAccess lock;auto r=post(body,revision);call(r);assert(r.status=="409 Conflict");}
 auto scaled=body;auto p=scaled.find("\"units_per_count\":1");scaled.replace(p,19,"\"units_per_count\":2");auto change=post(scaled,revision);call(change);assert(change.status=="409 Conflict");
 assert(disk.read(directory+"/meter-profile.json",stored)==ConfigJournal::Read::Ok&&stored==body);
 assert(disk.writeSync(directory+"/meter-profile.json.journal","damaged"));httpd_req_t damaged;call(damaged);assert(damaged.status=="503 Service Unavailable");
 std::cout<<"Profile API: save/readback, revision conflicts, body bounds, guards, scale refusal and damaged journal passed\n";
}
