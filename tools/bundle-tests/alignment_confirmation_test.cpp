#include "PolarAlignment.h"
#include <cassert>
#include <limits>
#include <cstdio>
int main(){
 using namespace polar;
 MarkerMatch a{0,0,5,7,1},b{100,0,105,7,1},c{50,100,55,107,1};
 double m[6],expected[6];assert(registration(a,b,expected)==AlignmentStatus::Ok);
 assert(confirmedRegistration(a,b,c,3,m)==AlignmentStatus::Ok);
 for(int i=0;i<6;++i)assert(m[i]==expected[i]);
 for(int mode=0;mode<6;++mode){auto bad=c;auto aa=a;double tolerance=3;
  if(mode==0)bad.foundX+=3.001;
  if(mode==1)bad.correlation=.79;
  if(mode==2)bad.foundY=std::numeric_limits<double>::quiet_NaN();
  if(mode==3){bad.targetY=0;bad.foundY=7;}
  if(mode==4)tolerance=0;
  if(mode==5)aa.targetX=std::numeric_limits<double>::infinity();
  for(double& x:m)x=99;
  assert(confirmedRegistration(aa,b,bad,tolerance,m)!=AlignmentStatus::Ok);
  for(double x:m)assert(x==99);
 }
 c.foundX+=3;assert(confirmedRegistration(a,b,c,3,m)==AlignmentStatus::Ok);
 puts("Third-marker agreement, unchanged transform, residual boundary and six rejection cases passed");
}
