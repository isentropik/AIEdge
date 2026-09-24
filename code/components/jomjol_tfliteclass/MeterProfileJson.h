#pragma once
#include "MeterProfile.h"
#include "cJSON.h"
#include <string>
#include <cstring>
namespace meter {
inline MeterKind parseKind(const char* s) {
 if(!s)return MeterKind::Unknown;
 if(!std::strcmp(s,"gas"))return MeterKind::Gas;
 if(!std::strcmp(s,"water"))return MeterKind::Water;
 if(!std::strcmp(s,"electricity"))return MeterKind::Electricity;
 return MeterKind::Unknown;
}
inline RegisterUnit parseUnit(const char* s) {
 if(!s)return RegisterUnit::Unknown;
 const char* names[]={"ft3","m3","L","US_gal","imp_gal","Wh","kWh"};
 const RegisterUnit units[]={RegisterUnit::CubicFoot,RegisterUnit::CubicMetre,RegisterUnit::Litre,RegisterUnit::USGallon,RegisterUnit::ImperialGallon,RegisterUnit::Wh,RegisterUnit::KWh};
 for(int i=0;i<7;++i)if(!std::strcmp(s,names[i]))return units[i];
 return RegisterUnit::Unknown;
}
// Strict versioned document. Unknown keys, duplicates and coercion are rejected.
inline bool parseProfile(const std::string& bytes,RegisterProfile& output) {
 if(bytes.empty()||bytes.size()>2048||bytes.find('\0')!=std::string::npos||bytes.find('\\')!=std::string::npos)return false;
 cJSON* root=cJSON_ParseWithLengthOpts(bytes.c_str(),bytes.size()+1,nullptr,1);
 if(!root)return false;
 struct Cleanup{cJSON* p;~Cleanup(){cJSON_Delete(p);}} cleanup{root};
 if(!cJSON_IsObject(root))return false;
 const char* names[]={"version","kind","source_unit","display_unit","units_per_count","has_secondary","secondary_units_per_revolution","confirmed"};
 cJSON* fields[8]={};
 for(auto* c=root->child;c;c=c->next){
  int index=-1;for(int i=0;i<8;++i)if(c->string&&!std::strcmp(c->string,names[i]))index=i;
  if(index<0||fields[index])return false;fields[index]=c;
 }
 for(auto* f:fields)if(!f)return false;
 if(!cJSON_IsNumber(fields[0])||fields[0]->valuedouble!=1||!cJSON_IsString(fields[1])||
 !cJSON_IsString(fields[2])||!cJSON_IsString(fields[3])||!cJSON_IsNumber(fields[4])||
 !cJSON_IsBool(fields[5])||!cJSON_IsNumber(fields[6])||!cJSON_IsTrue(fields[7]))return false;
 RegisterProfile next;next.kind=parseKind(fields[1]->valuestring);
 next.sourceUnit=parseUnit(fields[2]->valuestring);next.displayUnit=parseUnit(fields[3]->valuestring);
 next.unitsPerRegisterCount=fields[4]->valuedouble;next.hasSecondary=cJSON_IsTrue(fields[5]);
 next.secondaryUnitsPerRevolution=fields[6]->valuedouble;next.confirmed=true;
 if(!validProfile(next))return false;
 output=next;return true;
}
}
