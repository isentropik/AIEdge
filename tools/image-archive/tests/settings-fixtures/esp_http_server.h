
#pragma once
#include <string>
#include <map>
#include <cstring>
#include <algorithm>
using esp_err_t=int;
constexpr int ESP_OK=0,HTTP_GET=1,HTTP_POST=2;
struct httpd_req_t {int method=HTTP_GET,content_len=0;std::string input,output,status;size_t consumed=0;int failAfter=-1;size_t query=0;std::map<std::string,std::string> headers,responseHeaders;};
inline size_t httpd_req_get_url_query_len(httpd_req_t* r){return r->query;}
inline int httpd_req_get_hdr_value_str(httpd_req_t* r,const char* key,char* value,size_t size){auto i=r->headers.find(key);if(i==r->headers.end()||i->second.size()>=size)return -1;std::memcpy(value,i->second.c_str(),i->second.size()+1);return 0;}
inline int httpd_req_recv(httpd_req_t* r,char* bytes,size_t size){if(r->failAfter>=0&&r->consumed>=size_t(r->failAfter))return -1;size=std::min(size,std::min(size_t(13),r->input.size()-r->consumed));std::memcpy(bytes,r->input.data()+r->consumed,size);r->consumed+=size;return size;}
inline int httpd_resp_set_status(httpd_req_t* r,const char* s){r->status=s;return 0;}
inline int httpd_resp_set_type(httpd_req_t* r,const char* s){r->responseHeaders["Content-Type"]=s;return 0;}
inline int httpd_resp_set_hdr(httpd_req_t* r,const char* k,const char* v){r->responseHeaders[k]=v;return 0;}
inline int httpd_resp_sendstr(httpd_req_t* r,const char* s){r->output=s;return 0;}
