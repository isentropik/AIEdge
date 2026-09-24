#include "PolarAlignment.h"
#include <cassert>
#include <cstdio>
int main(){int count=0;
 for(double orientation: {0.,90.,179.,-179.})for(double rotation:{0.,1.,-1.,2.,-2.,2.01,-2.01,10.,-10.}){
 double pi=3.14159265358979323846,a=orientation*pi/180,b=(orientation+rotation)*pi/180;
 polar::MarkerMatch m{0,0,5,7,1},n{100*std::cos(a),100*std::sin(a),5+100*std::cos(b),7+100*std::sin(b),1};
 double matrix[6]={99,99,99,99,99,99};auto status=polar::registration(m,n,matrix);
 if(std::abs(rotation)>2){assert(status==polar::AlignmentStatus::Rotation);for(double x:matrix)assert(x==99);}
 else assert(status==polar::AlignmentStatus::Ok);++count;
 }printf("%d rotation-boundary and angle-wrap cases passed\n",count);
}