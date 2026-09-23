#pragma once
#include "ImprovSerial.h"
namespace AIEdgeWifi {
inline AIEdgeImprov::Bytes encode(const std::string& ssid,const std::string& password){
 if(!AIEdgeImprov::validCredentials(ssid,password))return {};
 AIEdgeImprov::Bytes out{1,static_cast<uint8_t>(ssid.size()),static_cast<uint8_t>(password.size())};
 out.insert(out.end(),ssid.begin(),ssid.end());out.insert(out.end(),password.begin(),password.end());return out;
}
inline bool decode(const AIEdgeImprov::Bytes& data,std::string& ssid,std::string& password){
 ssid.clear();password.clear();
 if(data.size()<3||data[0]!=1||data.size()!=size_t(3+data[1]+data[2]))return false;
 std::string name(data.begin()+3,data.begin()+3+data[1]);
 std::string pass(data.begin()+3+data[1],data.end());
 if(!AIEdgeImprov::validCredentials(name,pass))return false;
 ssid=name;password=pass;return true;
}
}
