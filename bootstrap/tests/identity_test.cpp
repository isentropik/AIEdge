#include "DeviceIdentity.h"
#include <cassert>
#include <cstdio>
#include <string>
#include <vector>
int main(){
 const uint8_t test[6]={0x20,0x9b,0xa9,0x74,0x4b,0x20};
 assert(AIEdgeIdentity::hostname(test)=="aiedge-744b20");
 const uint8_t zero[6]={0,0,0,0,1,2};assert(AIEdgeIdentity::hostname(zero)=="aiedge-000102");
 const uint8_t high[6]={0,0,0,255,254,253};assert(AIEdgeIdentity::hostname(high)=="aiedge-fffefd");
 // ESP-IDF builds the complete request line in its TX buffer. Exercise the
 // old overflow and the maximum accepted URL size including a signed query.
 std::string path="/asset?token="+std::string(890,'x');
 char oldBuffer[512];assert(snprintf(oldBuffer,sizeof oldBuffer,"GET %s HTTP/1.1\r\n",path.c_str())>=512);
 for(int n:{890,AIEdgeIdentity::maxReleaseUrlBytes}){
  std::string request(n,'x');std::vector<char> out(AIEdgeIdentity::httpRequestBufferBytes);
  assert(snprintf(out.data(),out.size(),"GET %s HTTP/1.1\r\n",request.c_str())<int(out.size()));
 }
 puts("PASS: unique hostname, zero padding, bounded GitHub request buffer");
}
