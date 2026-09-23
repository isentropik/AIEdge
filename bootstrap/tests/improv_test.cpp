#include "ImprovSerial.h"
#include <cassert>
#include <iostream>
using namespace AIEdgeImprov;
static Bytes credentials(const std::string& ssid,const std::string& pass){
 Bytes p{1,static_cast<uint8_t>(2+ssid.size()+pass.size()),static_cast<uint8_t>(ssid.size())};
 p.insert(p.end(),ssid.begin(),ssid.end());p.push_back(static_cast<uint8_t>(pass.size()));p.insert(p.end(),pass.begin(),pass.end());return p;
}
int main(){
 // Independent known protocol vector: get current state + sum of all header/data bytes.
 Bytes get{73,77,80,82,79,86,1,3,2,2,0,229};
 assert(frame(3,{2,0})==get);
 unsigned good=0,bad=0;Parser parser;
 auto packet=[&](const Bytes& data){Request r;assert(decode(data,r));assert(r.command==2);++good;};
 auto invalid=[&](){++bad;};
 for(auto b:get)parser.feed(b,packet,invalid);
 assert(good==1&&bad==0);
 // Serial output, partial reads and multiple requests must not confuse framing.
 for(auto b:std::string("booting\r\nIIMstatus\r\n"))parser.feed(b,packet,invalid);
 for(int n=0;n<20;++n)for(auto b:get)parser.feed(b,packet,invalid);
 assert(good==21&&bad==0);
 auto broken=get;broken.back()^=1;for(auto b:broken)parser.feed(b,packet,invalid);
 for(auto b:get)parser.feed(b,packet,invalid);assert(good==22&&bad==1);
 for(int i=0;i<8;++i)parser.feed(get[i],packet,invalid);
 parser.reset();for(auto b:get)parser.feed(b,packet,invalid);assert(good==23);
 // Every truncation and malformed credential length must be rejected.
 Request r;auto valid=credentials("Test network","test-pass-123");
 assert(decode(valid,r)&&r.ssid=="Test network"&&r.password=="test-pass-123");
 for(size_t n=0;n<valid.size();++n)assert(!decode(Bytes(valid.begin(),valid.begin()+n),r));
 auto extra=valid;extra.push_back(0);assert(!decode(extra,r));
 auto wrong=valid;wrong[2]=240;assert(!decode(wrong,r));
 assert(decode(credentials("Open",""),r));
 assert(!decode(credentials("","test-pass-123"),r));
 assert(!decode(credentials(std::string(32,'a'),"test-pass-123"),r));
 assert(!decode(credentials("test",std::string(64,'x')),r));
 assert(!decode(credentials("test","short"),r));
 assert(!decode(credentials(std::string("bad\0name",8),"test-pass-123"),r));
 assert(!decode(credentials("bad\nname","test-pass-123"),r));
 assert(!decode(credentials("test","bad\"pass-123"),r));
 for(uint8_t command=2;command<=4;++command){assert(decode({command,0},r));assert(!decode({command,1,0},r));}
 // State and scan terminators have exact packet structures/checksums.
 auto state=frame(1,{4});assert(state[7]==1&&state[8]==1&&state[9]==4);
 auto empty=result(4,{});assert(empty[7]==4&&empty[8]==2&&empty[9]==4&&empty[10]==0);
 auto scan=result(4,{"Network","-61","YES"});unsigned checksum=0;for(size_t i=0;i+1<scan.size();++i)checksum+=scan[i];assert((checksum&255)==scan.back());
 assert(result(3,{std::string(254,'x')}).empty());
 assert(frame(4,Bytes(256,0)).empty());
 std::cout<<"Improv framing, recovery, malformed credentials, limits, states and scan response checks passed\n";
}

