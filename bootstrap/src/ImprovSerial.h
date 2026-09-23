#pragma once
// Original AIEdge implementation of the public Improv Wi-Fi serial protocol.
// Protocol: https://www.improv-wifi.com/serial/ (ESPHome / Home Assistant).
#include <cstdint>
#include <string>
#include <vector>
#include <functional>
namespace AIEdgeImprov {
using Bytes = std::vector<uint8_t>;
inline Bytes frame(uint8_t type, const Bytes& data) {
    if (data.size()>255) return {};
    Bytes out{'I','M','P','R','O','V',1,type,static_cast<uint8_t>(data.size())};
    out.insert(out.end(),data.begin(),data.end());
    uint8_t sum=0; for (auto b:out) sum=static_cast<uint8_t>(sum+b);
    out.push_back(sum); return out;
}
inline Bytes result(uint8_t command, const std::vector<std::string>& strings) {
    Bytes data{command,0};
    for (const auto& value:strings) {
        if (value.size()>255 || data.size()+1+value.size()>255) return {};
        data.push_back(static_cast<uint8_t>(value.size()));
        data.insert(data.end(),value.begin(),value.end());
    }
    data[1]=static_cast<uint8_t>(data.size()-2); return frame(4,data);
}
inline bool validCredentials(const std::string& name,const std::string& password) {
    return !name.empty() && name.size()<=31 && password.size()<=63 &&
        (password.empty() || password.size()>=8) &&
        name.find_first_of("\r\n\"")==std::string::npos && name.find('\0')==std::string::npos &&
        password.find_first_of("\r\n\"")==std::string::npos && password.find('\0')==std::string::npos;
}
struct Request { uint8_t command=0; std::string ssid,password; };
inline bool decode(const Bytes& data,Request& out) {
    out=Request{};
    if (data.size()<2 || data[1]!=data.size()-2) return false;
    out.command=data[0];
    if (out.command!=1) return data.size()==2;
    size_t pos=2;
    auto read=[&](std::string& value){
        if(pos>=data.size()) return false;
        size_t length=data[pos++]; if(length>data.size()-pos) return false;
        value.assign(reinterpret_cast<const char*>(data.data()+pos),length);pos+=length;return true;
    };
    return read(out.ssid)&&read(out.password)&&pos==data.size()&&validCredentials(out.ssid,out.password);
}
class Parser {
    Bytes input;
public:
    void reset(){input.clear();}
    void feed(uint8_t byte,const std::function<void(const Bytes&)>& packet,const std::function<void()>& invalid) {
        static const uint8_t header[]={'I','M','P','R','O','V'};
        if(input.size()<6){
            if(byte!=header[input.size()]){input.clear();if(byte=='I')input.push_back(byte);return;}
            input.push_back(byte);return;
        }
        input.push_back(byte);
        if(input.size()==7 && byte!=1){reset();invalid();return;}
        if(input.size()<9 || input.size()<static_cast<size_t>(10+input[8]))return;
        uint8_t sum=0;for(size_t i=0;i+1<input.size();++i)sum=static_cast<uint8_t>(sum+input[i]);
        const bool ok=sum==input.back()&&input[7]==3;
        Bytes data(input.begin()+9,input.end()-1);reset();
        if(ok)packet(data);else invalid();
    }
};
}
