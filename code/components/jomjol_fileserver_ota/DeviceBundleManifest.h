#pragma once
#include "ArchiveInventory.h"
#include "cJSON.h"
#include <initializer_list>
#include <set>
#include <cstring>

namespace MeterBundle {
struct File {uint32_t bytes=0;std::string hash;};
struct Manifest {std::string id,appHash,modelHash,bootPolicy;File firmware;std::map<std::string,File> assets;};
inline bool hashValid(const std::string& s){if(s.size()!=64)return false;for(char c:s)if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')))return false;return true;}
inline bool fields(cJSON* object,std::initializer_list<const char*> names){
 if(!cJSON_IsObject(object))return false;
 std::set<std::string> seen;
 for(auto* c=object->child;c;c=c->next){if(!c->string||!seen.insert(c->string).second)return false;
  bool known=false;for(auto n:names)if(std::strcmp(n,c->string)==0)known=true;if(!known)return false;}
 return seen.size()==names.size();
}
inline std::string text(cJSON* object,const char* name){auto* v=cJSON_GetObjectItemCaseSensitive(object,name);return cJSON_IsString(v)&&v->valuestring?v->valuestring:"";}
inline bool file(cJSON* object,File& out){
 auto* n=cJSON_GetObjectItemCaseSensitive(object,"bytes");
 if(!cJSON_IsNumber(n)||!(n->valuedouble>=0&&n->valuedouble<=ArchiveInventory::maximumFileBytes)||n->valuedouble!=static_cast<uint32_t>(n->valuedouble))return false;
 out.bytes=static_cast<uint32_t>(n->valuedouble);out.hash=text(object,"sha256");return hashValid(out.hash);
}
inline std::string fileJson(const File& f){return "{\"bytes\":"+std::to_string(f.bytes)+",\"sha256\":\""+f.hash+"\"}";}
template<class Sha> bool parse(const std::string& body,Manifest& out,Sha sha){
 out=Manifest{};if(body.empty()||body.size()>128*1024)return false;
 // Machine-written ASCII schema: no escaped names, arrays or deep recursion.
 bool quoted=false;int depth=0;
 for(unsigned char c:body){if(c==0||c=='\\'||c>126)return false;if(c=='"'){quoted=!quoted;continue;}
  if(quoted){if(c<32)return false;continue;}if(c=='['||c==']')return false;
  if(c=='{'&&++depth>3)return false;
  if(c=='}'&&--depth<0)return false;}
 if(quoted||depth!=0)return false;
 cJSON* root=cJSON_ParseWithLengthOpts(body.c_str(),body.size()+1,nullptr,1);if(!root)return false;
 struct Cleanup{cJSON* p;~Cleanup(){cJSON_Delete(p);}} cleanup{root};
 if(!fields(root,{"format","chip","firmware","model_sha256","assets","bundle_id","boot_policy"})||text(root,"format")!="meter-bundle-v2"||text(root,"chip")!="esp32")return false;
 Manifest next;next.bootPolicy=text(root,"boot_policy");
 if(next.bootPolicy!="required_bundle"&&next.bootPolicy!="optional_bundle")return false;
 next.id=text(root,"bundle_id");next.modelHash=text(root,"model_sha256");
 if(!hashValid(next.id)||!hashValid(next.modelHash))return false;
 auto* firmware=cJSON_GetObjectItemCaseSensitive(root,"firmware");
 if(!fields(firmware,{"path","bytes","sha256","app_image_sha256"})||text(firmware,"path")!="firmware/firmware.bin"||!file(firmware,next.firmware)||!next.firmware.bytes)return false;
 next.appHash=text(firmware,"app_image_sha256");if(!hashValid(next.appHash))return false;
 ArchiveInventory inventory;if(!inventory.add("firmware/firmware.bin",false,next.firmware.bytes))return false;
 auto* assets=cJSON_GetObjectItemCaseSensitive(root,"assets");if(!cJSON_IsObject(assets))return false;
 for(auto* c=assets->child;c;c=c->next){
  if(!c->string||!fields(c,{"bytes","sha256"}))return false;
  const std::string name=c->string;File f;
  if(!(name.compare(0,5,"html/")==0||name.compare(0,6,"model/")==0||name.compare(0,12,"diagnostics/")==0)||!file(c,f)||!inventory.add(name,false,f.bytes))return false;
  if(!next.assets.emplace(name,f).second)return false;
 }
 const auto model=next.assets.find("model/polar-int8.tflite");
 if(model==next.assets.end()||model->second.hash!=next.modelHash||!model->second.bytes||!next.assets.count("html/index.html"))return false;
 std::string canonical="{\"assets\":{";bool first=true;
 for(const auto& a:next.assets){if(!first)canonical+=",";first=false;canonical+="\""+a.first+"\":"+fileJson(a.second);}
 canonical+="},\"boot_policy\":\""+next.bootPolicy+"\",\"chip\":\"esp32\",\"firmware\":{\"app_image_sha256\":\""+next.appHash+"\",\"bytes\":"+std::to_string(next.firmware.bytes)+",\"path\":\"firmware/firmware.bin\",\"sha256\":\""+next.firmware.hash+"\"},\"format\":\"meter-bundle-v2\",\"model_sha256\":\""+next.modelHash+"\"}";
 if(sha(canonical)!=next.id)return false;
 out=next;return true;
}
}
