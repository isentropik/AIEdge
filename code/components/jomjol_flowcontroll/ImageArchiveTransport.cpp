#include "ImageArchiveTransport.h"
#include "ImageArchiveSha.h"
#include "ImageSpoolFile.h"
#include "ImageArchiveReceipt.h"
#include "ImageArchiveSettings.h"
#include "ImageSettingsFile.h"
#include "esp_http_client.h"
#include "esp_timer.h"
#include "mbedtls/base64.h"
#include <algorithm>

namespace ImageArchive {
static UploadAttempt uploadSettings(const Destination& d,const std::string& hash,const std::string& descriptor) {
    UploadAttempt result;
    const std::string url="https://"+d.host+":"+std::to_string(d.port)+"/v1/settings";
    const std::string authorization="Bearer "+d.token;
    esp_http_client_config_t config={};
    config.url=url.c_str();config.cert_pem=d.certificatePem.c_str();
    config.method=HTTP_METHOD_POST;config.timeout_ms=d.timeoutMs;
    config.disable_auto_redirect=true;config.skip_cert_common_name_check=false;
    auto client=esp_http_client_init(&config);
    if(!client){result.error="settings_client_failed";return result;}
    struct Cleanup {esp_http_client_handle_t c;~Cleanup(){esp_http_client_close(c);esp_http_client_cleanup(c);}} cleanup{client};
    const int64_t deadline=esp_timer_get_time()+static_cast<int64_t>(d.timeoutMs)*1000;
    auto timeLeft=[&](){const int64_t remaining=deadline-esp_timer_get_time();return remaining>0 &&
        esp_http_client_set_timeout_ms(client,static_cast<int>(std::max<int64_t>(1,remaining/1000)))==ESP_OK;};
    if(esp_http_client_set_header(client,"Authorization",authorization.c_str())!=ESP_OK ||
       esp_http_client_set_header(client,"Content-Type","application/octet-stream")!=ESP_OK ||
       esp_http_client_set_header(client,"X-Settings-SHA256",hash.c_str())!=ESP_OK) {
        result.error="settings_headers_failed";return result;
    }
    if(!timeLeft() || esp_http_client_open(client,descriptor.size())!=ESP_OK){result.error="settings_connection_failed";return result;}
    size_t sent=0;
    while(sent<descriptor.size()) {
        if(!timeLeft()){result.error="settings_timeout";return result;}
        const int n=esp_http_client_write(client,descriptor.data()+sent,descriptor.size()-sent);
        if(n<=0 || static_cast<size_t>(n)>descriptor.size()-sent){result.error="settings_write_failed";return result;}
        sent+=n;
    }
    if(!timeLeft() || esp_http_client_fetch_headers(client)<0){result.error="settings_response_failed";return result;}
    result.status=esp_http_client_get_status_code(client);
    if(result.status!=200 && result.status!=201){result.error="settings_rejected";return result;}
    std::string body;char buffer[513];
    while(!esp_http_client_is_complete_data_received(client)) {
        if(!timeLeft()){result.status=0;result.error="settings_response_timeout";return result;}
        const int n=esp_http_client_read(client,buffer,sizeof(buffer)-body.size());
        if(n<0){result.status=0;result.error="settings_response_read_failed";return result;}
        if(n==0)break;
        body.append(buffer,n);
        if(body.size()>512){result.error="settings_receipt_too_large";return result;}
    }
    if(!esp_http_client_is_complete_data_received(client)){result.status=0;result.error="settings_response_incomplete";return result;}
    if(!settingsReceiptMatches(body,hash)){result.error="settings_receipt_invalid";return result;}
    result.error=nullptr;return result;
}
UploadAttempt uploadSpool(const std::string& root,const Ticket& ticket,const Destination& d) {
    UploadAttempt result;
    if(!ticket.identity.valid() || !validArchiveDestination(d)){result.error="invalid_destination_or_identity";return result;}
    const auto path=root+"/"+ticket.identity.capture+".spool";
    CaptureMetadata metadata;UploadRecord record;
    if(readSpoolFile<Sha256>(path,metadata,record)!=SpoolResult::Saved || !(record.identity==ticket.identity)) {
        result.error="spool_verification_failed";return result;
    }
    std::string settings;
    if(readSettingsFile<Sha256>(root,metadata.settingsHash,settings)!=SpoolResult::Saved) {
        result.error="settings_file_invalid_or_missing";return result;
    }
    const auto settingsAttempt=uploadSettings(d,metadata.settingsHash,settings);
    if(settingsAttempt.error)return settingsAttempt;
    unsigned char encoded[4097];size_t encodedSize=0;
    if(mbedtls_base64_encode(encoded,sizeof(encoded),&encodedSize,
        reinterpret_cast<const unsigned char*>(record.metadata.data()),record.metadata.size())!=0 || encodedSize>4096) {
        result.error="metadata_encoding_failed";return result;
    }
    const std::string metadataHeader(reinterpret_cast<char*>(encoded),encodedSize);
    const std::string url="https://"+d.host+":"+std::to_string(d.port)+"/v1/captures";
    const std::string authorization="Bearer "+d.token;
    esp_http_client_config_t config={};
    config.url=url.c_str();config.cert_pem=d.certificatePem.c_str();
    config.method=HTTP_METHOD_POST;config.timeout_ms=d.timeoutMs;
    config.disable_auto_redirect=true;config.skip_cert_common_name_check=false;
    auto client=esp_http_client_init(&config);
    if(!client){result.error="client_init_failed";return result;}
    struct ClientCleanup {esp_http_client_handle_t value;~ClientCleanup(){esp_http_client_close(value);esp_http_client_cleanup(value);}} cleanup{client};
    const int64_t deadline=esp_timer_get_time()+static_cast<int64_t>(d.timeoutMs)*1000;
    auto timeLeft=[&](){
        const int64_t remaining=deadline-esp_timer_get_time();
        return remaining>0 && esp_http_client_set_timeout_ms(client,static_cast<int>(std::max<int64_t>(1,remaining/1000)))==ESP_OK;
    };
    if(esp_http_client_set_header(client,"Authorization",authorization.c_str())!=ESP_OK ||
       esp_http_client_set_header(client,"Content-Type","application/octet-stream")!=ESP_OK ||
       esp_http_client_set_header(client,"X-Meter-Metadata",metadataHeader.c_str())!=ESP_OK) {
        result.error="request_headers_failed";return result;
    }
    FILE* file=std::fopen(path.c_str(),"rb");
    if(!file){result.error="spool_open_failed";return result;}
    struct FileCleanup {FILE* value;~FileCleanup(){if(value)std::fclose(value);}} fileCleanup{file};
    if(std::fseek(file,SpoolRecordBytes,SEEK_SET)!=0){result.error="spool_seek_failed";return result;}
    if(!timeLeft() || esp_http_client_open(client,metadata.imageBytes)!=ESP_OK){result.error="connection_failed";return result;}
    unsigned char buffer[4096];uint32_t remaining=metadata.imageBytes;Sha256 sentHash;
    while(remaining) {
        const size_t n=std::min<size_t>(remaining,sizeof(buffer));
        if(std::fread(buffer,1,n,file)!=n || !sentHash.update(buffer,n)){result.error="spool_read_failed";return result;}
        size_t offset=0;
        while(offset<n) {
            if(!timeLeft()){result.error="upload_timeout";return result;}
            const int written=esp_http_client_write(client,reinterpret_cast<char*>(buffer)+offset,n-offset);
            if(written<=0 || static_cast<size_t>(written)>n-offset){result.error="upload_write_failed";return result;}
            offset+=written;
        }
        remaining-=n;
    }
    const bool unchanged=std::fgetc(file)==EOF && !std::ferror(file) && sentHash.finish()==metadata.imageHash;
    const bool closed=std::fclose(file)==0;fileCleanup.value=nullptr;
    if(!unchanged || !closed){result.error="spool_changed_or_close_failed";return result;}
    if(!timeLeft() || esp_http_client_fetch_headers(client)<0){result.error="response_headers_failed";return result;}
    result.status=esp_http_client_get_status_code(client);
    if(result.status!=200 && result.status!=201){result.error="server_rejected";return result;}
    std::string body;
    while(!esp_http_client_is_complete_data_received(client)) {
        if(!timeLeft()){result.status=0;result.error="response_timeout";return result;}
        const int n=esp_http_client_read(client,reinterpret_cast<char*>(buffer),std::min<size_t>(sizeof(buffer),1025-body.size()));
        if(n<0){result.status=0;result.error="response_read_failed";return result;}
        if(n==0)break;
        body.append(reinterpret_cast<char*>(buffer),n);
        if(body.size()>1024){result.error="receipt_too_large";return result;}
    }
    if(!esp_http_client_is_complete_data_received(client)){result.status=0;result.error="response_incomplete";return result;}
    if(!parseReceipt(body,result.receipt) || !result.receipt.matches(ticket.identity)){result.error="receipt_invalid";return result;}
    result.error=nullptr;
    return result;
}
}
