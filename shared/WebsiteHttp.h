#pragma once
#include "WebsiteAccess.h"
#include "WebsiteSetupPage.h"
#include "WebsitePasswordPage.h"
#include "esp_http_server.h"
#include "mbedtls/base64.h"
#include "esp_timer.h"
#include <cstdio>
#include <cstring>
namespace AIEdgeAuth {
class WebsiteHttp {
    WebsiteAccess& access;
    static esp_err_t reply(httpd_req_t* req,const char* status,const char* text){
        httpd_resp_set_status(req,status);httpd_resp_set_type(req,"text/plain; charset=utf-8");
        httpd_resp_set_hdr(req,"Cache-Control","no-store");
        return httpd_resp_send(req,text,std::strlen(text));
    }
    static esp_err_t unavailable(httpd_req_t* req){return reply(req,"503 Service Unavailable","Website credentials could not be loaded. Settings have not been erased. Check USB diagnostics.");}
    static esp_err_t challenge(httpd_req_t* req){
        httpd_resp_set_hdr(req,"WWW-Authenticate","Basic realm=\"AIEdge\", charset=\"UTF-8\"");
        return reply(req,"401 Unauthorized","Sign in to AIEdge with username admin and your website password.");
    }
    static bool password(httpd_req_t* req,uint8_t* out,size_t& size){
        char header[256]={};uint8_t decoded[192]={};size_t count=0;
        const size_t n=httpd_req_get_hdr_value_len(req,"Authorization");
        if(n<7||n>=sizeof header||httpd_req_get_hdr_value_str(req,"Authorization",header,sizeof header)!=ESP_OK)return false;
        const char prefix[]="Basic ";unsigned mismatch=0;
        for(size_t i=0;i<5;++i)mismatch|=(header[i]|32)^(prefix[i]|32);
        bool ok=!mismatch&&header[5]==' '&&mbedtls_base64_decode(decoded,sizeof decoded,&count,reinterpret_cast<unsigned char*>(header+6),n-6)==0&&count>6&&count<=134&&!std::memcmp(decoded,"admin:",6);
        if(ok){size=count-6;std::memcpy(out,decoded+6,size);}
        wipe(decoded,sizeof decoded);wipe(header,sizeof header);return ok;
    }
    static bool body(httpd_req_t* req,uint8_t* out,size_t& size){
        if(req->content_len<12||req->content_len>128)return false;
        size=0;while(size<req->content_len){int got=httpd_req_recv(req,reinterpret_cast<char*>(out)+size,req->content_len-size);if(got<=0)return false;size+=got;}return true;
    }
    esp_err_t setup(httpd_req_t* req){
        if(access.state()!=State::NeedsSetup)return reply(req,"409 Conflict","Website password is already configured or storage is unavailable. Reload the page.");
        char encoded[65]={};uint8_t token[32]={},value[128]={};size_t size=0;
        bool ok=httpd_req_get_hdr_value_len(req,"X-AIEdge-Setup")==64&&httpd_req_get_hdr_value_str(req,"X-AIEdge-Setup",encoded,sizeof encoded)==ESP_OK;
        for(size_t i=0;ok&&i<64;++i){char c=encoded[i];int digit=c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:c>='A'&&c<='F'?c-'A'+10:-1;if(digit<0)ok=false;else token[i/2]|=digit<<((i%2)?0:4);}
        ok=ok&&body(req,value,size)&&access.setup(token,sizeof token,value,size);
        wipe(token,sizeof token);wipe(encoded,sizeof encoded);wipe(value,sizeof value);
        if(access.state()==State::StorageError)return unavailable(req);
        return reply(req,ok?"200 OK":"400 Bad Request",ok?"Password saved. Continue and sign in as admin.":"Password was not saved. Check the setup code and password requirements.");
    }
    esp_err_t change(httpd_req_t* req){
        char action[8]={};uint8_t oldValue[128]={},newValue[128]={};size_t oldSize=0,newSize=0;
        bool ok=httpd_req_get_hdr_value_len(req,"X-AIEdge-Password-Change")==7&&
            httpd_req_get_hdr_value_str(req,"X-AIEdge-Password-Change",action,sizeof action)==ESP_OK&&
            !std::memcmp(action,"confirm",7)&&password(req,oldValue,oldSize)&&body(req,newValue,newSize)&&
            access.change(oldValue,oldSize,newValue,newSize,esp_timer_get_time());
        wipe(oldValue,sizeof oldValue);wipe(newValue,sizeof newValue);wipe(action,sizeof action);
        if(access.state()==State::StorageError)return unavailable(req);
        return reply(req,ok?"200 OK":"400 Bad Request",ok?"Password changed. Sign in again with the new password.":"Password was not changed. Check the password requirements and try again.");
    }

public:
    explicit WebsiteHttp(WebsiteAccess& state):access(state){}
    void initialize(){
        uint8_t token[32]={};const auto state=access.initialize(token);
        if(state==State::NeedsSetup&&access.setupAvailable()){
            // USB stdout only: do not copy this secret into web diagnostics or files.
            char encoded[65]={};constexpr char hex[]="0123456789abcdef";
            for(size_t i=0;i<sizeof token;++i){encoded[2*i]=hex[token[i]>>4];encoded[2*i+1]=hex[token[i]&15];}
            std::printf("AIEdge website setup code: %s\n",encoded);wipe(encoded,sizeof encoded);
        }
        wipe(token,sizeof token);
    }
    // Called only by the physical USB parser, queued onto the HTTP server task.
    // Never invoke from an HTTP endpoint or publish replies through diagnostics.
    void localCommand(const char* command){
        if(!std::strcmp(command,"AIEdge AUTH SETUP")){
            if(access.state()==State::NeedsSetup)initialize();
            else std::printf("AIEdge website password is configured or storage needs recovery.\n");
            return;
        }
        if(!std::strcmp(command,"AIEdge AUTH RESET")){
            uint8_t token[16]={};char encoded[33]={};constexpr char hex[]="0123456789abcdef";
            if(access.beginLocalRecovery(esp_timer_get_time(),token)){
                for(size_t i=0;i<sizeof token;++i){encoded[2*i]=hex[token[i]>>4];encoded[2*i+1]=hex[token[i]&15];}
                std::printf("Remove only the website password? Within 60 seconds send: AIEdge AUTH CONFIRM %s\n",encoded);
            }else std::printf("AIEdge could not prepare password recovery; nothing changed.\n");
            wipe(token,sizeof token);wipe(encoded,sizeof encoded);return;
        }
        constexpr char prefix[]="AIEdge AUTH CONFIRM ";
        if(std::strncmp(command,prefix,sizeof prefix-1)==0){
            const char* encoded=command+sizeof prefix-1;uint8_t token[16]={};bool valid=std::strlen(encoded)==32;
            for(size_t i=0;valid&&i<32;++i){char c=encoded[i];int digit=c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:c>='A'&&c<='F'?c-'A'+10:-1;if(digit<0)valid=false;else token[i/2]|=digit<<((i%2)?0:4);}
            const bool done=access.confirmLocalRecovery(valid?token:nullptr,valid?sizeof token:0,esp_timer_get_time());
            wipe(token,sizeof token);
            if(done){std::printf("AIEdge website password removed. Wi-Fi and SD files preserved.\n");initialize();}
            else std::printf("AIEdge password reset not confirmed or storage verification failed. Request a new reset code or check USB diagnostics.\n");
            return;
        }
        std::printf("AIEdge USB commands: AUTH SETUP or AUTH RESET (prefix each with AIEdge).\n");
    }
    bool configured()const{return access.state()==State::Ready;}
    esp_err_t handle(httpd_req_t* req,esp_err_t(*handler)(httpd_req_t*)){
        const bool setupPath=!std::strcmp(req->uri,"/auth/setup");
        if(setupPath&&req->method==HTTP_POST)return setup(req);
        if(access.state()==State::NeedsSetup){
            if(!access.setupAvailable())return unavailable(req);
            if(req->method==HTTP_GET&&((req->uri[0]=='/'&&(req->uri[1]==0||req->uri[1]=='?'))||setupPath)){
                httpd_resp_set_type(req,"text/html; charset=utf-8");httpd_resp_set_hdr(req,"Cache-Control","no-store");
                return httpd_resp_send(req,setupPage,sizeof setupPage-1);
            }
            return reply(req,"423 Locked","Create the website password at the device home page first.");
        }
        if(access.state()!=State::Ready)return unavailable(req);
        uint8_t supplied[128]={};size_t size=0;
        const auto decision=password(req,supplied,size)?access.check(supplied,size,esp_timer_get_time()):Access::Unauthorized;
        wipe(supplied,sizeof supplied);
        if(decision==Access::RetryLater){httpd_resp_set_hdr(req,"Retry-After","1");return reply(req,"429 Too Many Requests","Wait a second before trying again.");}
        if(decision==Access::StorageError)return unavailable(req);
        if(decision!=Access::Allowed)return challenge(req);
        if(setupPath)return reply(req,"200 OK","Website password is already configured.");
        if(!std::strcmp(req->uri,"/auth/password")){
            if(req->method==HTTP_POST)return change(req);
            if(req->method==HTTP_GET){
                httpd_resp_set_type(req,"text/html; charset=utf-8");httpd_resp_set_hdr(req,"Cache-Control","no-store");
                return httpd_resp_send(req,passwordPage,sizeof passwordPage-1);
            }
        }
        return handler(req);
    }
};
}
