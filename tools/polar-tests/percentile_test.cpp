
#include "PolarPercentile.h"
#include <algorithm>
#include <cassert>
#include <cstring>
#include <random>
int main(){
 std::mt19937 rng(90323);double a[360],b[360];
 for(int mode=0;mode<6;++mode)for(int trial=0;trial<2000;++trial){
  for(int i=0;i<360;++i){
   switch(mode){
    case 0:a[i]=double(rng()%1000000)/4000;break;
    case 1:a[i]=rng()%256;break;
    case 2:a[i]=trial%256;break;
    case 3:a[i]=i/2.0;break;
    case 4:a[i]=(359-i)/2.0;break;
    default:a[i]=(i==trial%360)?255:0;
   }
  }
  std::copy(a,a+360,b);std::sort(a,a+360);polar::selectPercentile75(b);
  assert(a[269]==b[269]&&a[270]==b[270]);
  double old=a[269]*.75+a[270]*.25,now=b[269]*.75+b[270]*.25;
  assert(std::memcmp(&old,&now,sizeof(old))==0);
 }
}
