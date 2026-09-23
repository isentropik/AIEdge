#include "PolarWarp.h"
#include <cassert>
#include <cmath>
#include <cstring>
#include <random>
int main(){
 std::mt19937 rng(20260923);
 const double edges[]={0.0,std::nextafter(0.0,1.0),0.25,0.5,0.75,std::nextafter(1.0,0.0)};
 for(int i=0;i<200000;++i){
  uint8_t a=rng()%256,b=rng()%256,c=rng()%256,d=rng()%256;
  for(int j=0;j<7;++j){double f=j<6?edges[j]:double(rng())/4294967296.0;
   double reference=polar::cubic(a,b,c,d,f),actual=polar::cubicBytes(a,b,c,d,f);
   assert(std::memcmp(&reference,&actual,sizeof(double))==0);
  }
 }
 for(int mask=0;mask<16;++mask)for(double f:edges){
  uint8_t a=(mask&1)?255:0,b=(mask&2)?255:0,c=(mask&4)?255:0,d=(mask&8)?255:0;
  double x=polar::cubic(a,b,c,d,f),y=polar::cubicBytes(a,b,c,d,f);
  assert(std::memcmp(&x,&y,sizeof(double))==0);
 }
}
