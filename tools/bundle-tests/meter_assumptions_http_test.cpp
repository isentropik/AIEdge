#include "MeterAssumptionsSettingsHttp.h"
#include <cassert>
#include <iostream>
int64_t fake_time=0;
std::string field(const std::string&body,const char*key){auto*j=cJSON_Parse(body.c_str());assert(j);auto*v=cJSON_GetObjectItem(j,key);assert(cJSON_IsString(v));std::string result=v->valuestring;cJSON_Delete(j);return result;}
int main(int argc,char**argv){assert(argc==2);std::string directory=argv[1];ConfigStorage::Files disk;
 meter::AccountingController controller(directory,std::string(64,'a'),std::string(64,'b'));int changed=0;
 auto call=[&](httpd_req_t&r){assert(meter::handleAssumptionsSettings(&r,directory,controller,[&](){++changed;})==ESP_OK);assert(r.responseHeaders["Cache-Control"]=="no-store");assert(!r.responseHeaders.count("Access-Control-Allow-Origin"));};
 httpd_req_t get;call(get);assert(get.status=="200 OK"&&get.output.find("\"initialized\":false")!=std::string::npos);auto revision=field(get.output,"revision");
 assert(!controller.active()&&changed==0);
 const std::string body=R"({"version":1,"maximum_flow_ft3_hour":360})";
 auto post=[&](std::string bytes,std::string rev){httpd_req_t r;r.method=HTTP_POST;r.input=bytes;r.content_len=bytes.size();r.headers["Content-Type"]="application/json";r.headers["X-AIEdge-Revision"]=rev;return r;};
 auto save=post(body,revision);call(save);assert(save.status=="200 OK"&&field(save.output,"status")=="saved_and_active");
 assert(controller.active()&&controller.current().assumptions.maximumRateFt3S==.1&&changed==1);
 std::string stored;assert(disk.read(directory+"/meter-assumptions.json",stored)==ConfigJournal::Read::Ok&&stored==body);
 auto stale=post(body,revision);call(stale);assert(stale.status=="409 Conflict"&&changed==1);
 httpd_req_t reread;call(reread);revision=field(reread.output,"revision");assert(reread.output.find("\"saved_active\":true")!=std::string::npos);
 auto bad=post(body,revision);bad.headers.erase("X-AIEdge-Revision");call(bad);assert(bad.status=="400 Bad Request");
 bad=post(body,revision);bad.failAfter=0;call(bad);assert(bad.status=="400 Bad Request");
 bad=post(body,revision);bad.content_len=513;call(bad);assert(bad.status=="413 Payload Too Large");
 bad=post(body,revision);bad.method=99;call(bad);assert(bad.status=="405 Method Not Allowed");
 bad=post(body,revision);bad.query=1;call(bad);assert(bad.status=="400 Bad Request");
 bad=post(R"({"version":1,"maximum_flow_ft3_hour":0})",revision);call(bad);assert(bad.status=="400 Bad Request");
 {ProcessingAccess lock;auto r=post(body,revision);call(r);assert(r.status=="409 Conflict");}
 {UpdateAccess lock;auto r=post(body,revision);call(r);assert(r.status=="409 Conflict");}
 assert(changed==1);
 // Saving succeeds but damaged target history prevents activation: retain old runtime.
 assert(disk.writeSync(directory+"/polar-meter-reference.0","damaged"));
 auto disable=post(R"({"version":1,"maximum_flow_ft3_hour":null})",revision);call(disable);
 assert(disable.status=="200 OK"&&field(disable.output,"status")=="saved_not_active");
 assert(controller.current().assumptions.hasMaximumRate&&changed==2);
 httpd_req_t pending;call(pending);assert(pending.output.find("\"saved_active\":false")!=std::string::npos);
 assert(disk.writeSync(directory+"/meter-assumptions.json.journal","damaged"));
 httpd_req_t damaged;call(damaged);assert(damaged.status=="503 Service Unavailable");
 assert(controller.current().assumptions.hasMaximumRate&&changed==2);
 std::cout<<"PASS: flow API read/save, stale requests, guards, input bounds and saved-not-active recovery status\n";
}
