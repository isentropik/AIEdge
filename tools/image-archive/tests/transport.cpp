
#include "ImageArchiveTransport.h"
#include "ImageArchiveSha.h"
#include "ImageSpoolFile.h"
#include "ImageSettingsFile.h"
#include "esp_http_client.h"
#include <cassert>
#include <cstring>
#include <iostream>
#include <algorithm>
using namespace ImageArchive;
int mode=0,inits=0,closes=0,cleanups=0;size_t position=0;int64_t clockUs=0;
std::string response,sent,expected,imageResponse,settingsResponse,descriptor;bool settingsPhase=false;int effectiveMode=0,txSize=0;bool sharedBudget=false;int lastTimeout=0;
void* esp_http_client_init(const esp_http_client_config_t* c){
    txSize=c->buffer_size_tx?c->buffer_size_tx:512;
    ++inits;settingsPhase=std::string(c->url).find("/v1/settings")!=std::string::npos;
    effectiveMode=mode>=20 ? (settingsPhase?0:mode-20) : mode;
    position=0;sent.clear();response=settingsPhase?settingsResponse:imageResponse;
    if(effectiveMode==7)response=std::string(1025,'x');if(effectiveMode==11)response="{}";
    assert(c->disable_auto_redirect && !c->skip_cert_common_name_check);
    assert(std::string(c->url)==(settingsPhase?"https://storage.local:8766/v1/settings":"https://storage.local:8766/v1/captures"));
    assert(c->cert_pem && c->method==HTTP_METHOD_POST);return effectiveMode==1?nullptr:reinterpret_cast<void*>(1);
}
int esp_http_client_close(void*){++closes;return 0;}int esp_http_client_cleanup(void*){++cleanups;return 0;}
int esp_http_client_set_timeout_ms(void*,int n){assert(n>0&&n<=15000);lastTimeout=n;return effectiveMode==13?-1:0;}
int esp_http_client_set_header(void*,const char* name,const char* value){
    if(std::string(name)=="X-Meter-Metadata"){
        assert(strlen(value)>512); // Actual record reproduces the former default-buffer failure.
        assert(strlen(name)+strlen(value)+7 < static_cast<size_t>(txSize));
        assert(txSize<=5120); // Bounded allocation even at the metadata limit.
    }
    return effectiveMode==2?-1:0;
}
int esp_http_client_open(void*,int n){assert(n==static_cast<int>(settingsPhase?descriptor.size():expected.size()));if(sharedBudget){int needed=10000;if(lastTimeout<needed){clockUs+=int64_t(lastTimeout)*1000;return -1;}clockUs+=int64_t(needed)*1000;}return effectiveMode==3?-1:0;}
int esp_http_client_write(void*,const char* data,int n){if(effectiveMode==4)return -1;int amount=std::min(n,37);sent.append(data,amount);return amount;}
int64_t esp_http_client_fetch_headers(void*){assert(sent==(settingsPhase?descriptor:expected));return effectiveMode==5?-1:response.size();}
int esp_http_client_get_status_code(void*){return effectiveMode==6?401:(effectiveMode==12?200:201);}
bool esp_http_client_is_complete_data_received(void*){return effectiveMode!=8 && position==response.size();}
int esp_http_client_read(void*,char* data,int n){if(effectiveMode==9)return -1;auto amount=std::min<size_t>(n,std::min<size_t>(31,response.size()-position));std::memcpy(data,response.data()+position,amount);position+=amount;return amount;}
int64_t esp_timer_get_time(){clockUs+=effectiveMode==10?8000000:1;return clockUs;}
int main(int argc,char**argv){
    assert(argc==2);std::string root=argv[1];expected=std::string(9001,'x');
    CaptureMetadata m;m.device="meter";m.boot="boot";m.imageBytes=expected.size();
    m.imageHash=hashBytes<Sha256>(expected);m.firmwareHash=std::string(64,'1');m.modelHash=std::string(64,'2');
    m.calibrationHash=std::string(64,'3');descriptor="capture-settings-v1\nsource=driver-status-and-capture-config\n";
    m.settingsHash=hashBytes<Sha256>(descriptor);assert(writeSettingsFile<Sha256>(root,m.settingsHash,descriptor)==SpoolResult::Saved);
    settingsResponse="{\"version\":1,\"settings_sha256\":\""+m.settingsHash+"\",\"verified_readback\":true,\"duplicate\":false}";
    assert(writeSpoolFile<Sha256>(root,m,reinterpret_cast<const unsigned char*>(expected.data()),expected.size())==SpoolResult::Saved);
    UploadRecord record;assert(buildRecord(m,hashBytes<Sha256>,record));Ticket t;t.identity=record.identity;
    const auto good="{\"version\":1,\"capture_id\":\""+t.identity.capture+"\",\"image_sha256\":\""+t.identity.image+
        "\",\"record_sha256\":\""+t.identity.record+"\",\"duplicate\":false,\"verified_readback\":true,\"review_status\":\"unreviewed\",\"training_eligible\":false}";
    Destination d;d.host="storage.local";d.token=std::string(40,'a');d.certificatePem="test certificate";
    imageResponse=good;
    for(mode=0;mode<=33;++mode){
        if(mode>=14 && mode<20)continue;
        inits=closes=cleanups=0;clockUs=0;position=0;sent.clear();response=good;
        if(mode==7)response=std::string(1025,'x');if(mode==11)response="{}";
        auto result=uploadSpool(root,t,d);
        const bool second=(mode>=20 || mode==0 || mode==12);assert(inits==(second?2:1));
        assert(cleanups==inits-((mode==1||mode==21)?1:0));assert(closes==cleanups);
        if(mode==0||mode==12||mode==20||mode==32){assert(result.error==nullptr);assert(result.receipt.matches(t.identity));}
        else{assert(result.error!=nullptr);assert(!result.receipt.matches(t.identity));}
        // No upload path deletes the pending local source.
        CaptureMetadata loaded;UploadRecord r;
        assert(readSpoolFile<Sha256>(root+"/"+t.identity.capture+".spool",loaded,r)==SpoolResult::Saved);
    }
    // Two individually sub-timeout requests must share one upload budget.
    mode=0;effectiveMode=0;clockUs=0;inits=closes=cleanups=0;sharedBudget=true;
    auto slow=uploadSpool(root,t,d);
    assert(slow.error && !slow.receipt.matches(t.identity));
    assert(clockUs<=15001000 && inits==2 && cleanups==2 && closes==2);
    CaptureMetadata retained;UploadRecord retainedRecord;
    assert(readSpoolFile<Sha256>(root+"/"+t.identity.capture+".spool",retained,retainedRecord)==SpoolResult::Saved);
    sharedBudget=false;clockUs=0;
    auto retry=uploadSpool(root,t,d);assert(!retry.error && retry.receipt.matches(t.identity));
    const auto settingsPath=root+"/"+m.settingsHash+".settings";
    assert(std::rename(settingsPath.c_str(),(settingsPath+".pending").c_str())==0);
    inits=0;assert(uploadSpool(root,t,d).error);assert(inits==0);
    assert(std::rename((settingsPath+".pending").c_str(),settingsPath.c_str())==0);
    for(auto host:{"storage.local/path","user@storage","storage\r\nInjected","https://storage"}){
        d.host=host;inits=0;assert(uploadSpool(root,t,d).error);assert(inits==0);
    }
    d.host="storage.local";d.certificatePem.clear();inits=0;assert(uploadSpool(root,t,d).error);assert(inits==0);
    std::cout<<"28 settings-first/image transport outcomes plus shared-deadline timeout/retry and invalid destinations passed with real spool/SHA and partial HTTP writes\n";
}
