#include "PolarAlignment.h"
#include <vector>
#include <cassert>
#include <cstdio>
int main(){
 const int w=90,h=80,mw=7,mh=7,tx=40,ty=35;
 std::vector<uint8_t> image(w*h,100),marker(mw*mh);
 unsigned state=7;for(auto& v:marker){state=state*1664525u+1013904223u;v=30+(state>>24)%190;}
 auto paste=[&](int x,int y,bool altered){for(int j=0;j<mh;++j)for(int i=0;i<mw;++i)image[(y+j)*w+x+i]=marker[j*mw+i]+(altered && i==0 ? 1:0);};
 double scores[1681];polar::MarkerMatch m{99,99,99,99,99};
 paste(tx,ty,false);
 assert(polar::matchMarker(image.data(),w,h,marker.data(),mw,mh,tx,ty,scores,1681,m)==polar::AlignmentStatus::Ok);
 for(bool altered:{false,true}){
  paste(tx+12,ty,altered);m={99,99,99,99,99};
  assert(polar::matchMarker(image.data(),w,h,marker.data(),mw,mh,tx,ty,scores,1681,m)==polar::AlignmentStatus::Ambiguous);
  assert(m.targetX==99 && m.targetY==99 && m.foundX==99 && m.foundY==99 && m.correlation==99);
 }
 puts("Unique marker accepted; exact and near-duplicate markers rejected without mutating output");
}
