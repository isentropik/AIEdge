#include "PolarAlignment.h"
#include <cassert>
#include <cstring>
#include <vector>
#include <cstdio>

// Original per-pixel int64 arithmetic, independent of the optimized loop.
void reference(const std::vector<uint8_t>& image,int w,int h,const std::vector<uint8_t>& marker,
               int mw,int mh,int tx,int ty,double* scores) {
    int64_t ts=0,tq=0;const double n=mw*mh;
    for(auto value:marker){ts+=value;tq+=int(value)*value;}
    const double tv=std::max(0.0,tq-double(ts)*ts/n);
    assert(tv>=1);
    for(int dy=-20;dy<=20;++dy)for(int dx=-20;dx<=20;++dx){
        int k=(dy+20)*41+dx+20,x=tx+dx,y=ty+dy;scores[k]=-1;
        if(x<0||y<0||x+mw>w||y+mh>h)continue;
        int64_t ps=0,pq=0,dot=0;
        for(int row=0;row<mh;++row)for(int col=0;col<mw;++col){
            int p=image[(y+row)*w+x+col];ps+=p;pq+=p*p;dot+=p*marker[row*mw+col];
        }
        const double pv=std::max(0.0,pq-double(ps)*ps/n);
        scores[k]=(dot-double(ts)*ps/n)/std::max(1e-9,std::sqrt(tv*pv));
    }
}
int main(){
    uint32_t random=20260924;
    const int sizes[][4]={{100,90,13,17},{100,90,31,25},{4096,10,4096,9},{100,100,90,90},{640,480,24,24}};
    int cases=0,accepted=0;
    for(const auto& size:sizes)for(int mode=0;mode<4;++mode)for(int edge=0;edge<3;++edge){
        int w=size[0],h=size[1],mw=size[2],mh=size[3];
        std::vector<uint8_t> image(w*h),marker(mw*mh);
        for(auto& value:image){random=random*1664525u+1013904223u;value=mode==0?255:mode==1?0:static_cast<uint8_t>(random>>24);}
        int tx=edge==0?0:edge==1?w-mw:(w-mw)/2,ty=edge==0?0:edge==1?h-mh:(h-mh)/2;
        for(int r=0;r<mh;++r)for(int c=0;c<mw;++c){
            random=random*1664525u+1013904223u;
            marker[r*mw+c]=mode==3?image[(ty+r)*w+tx+c]:static_cast<uint8_t>(random>>24);
        }
        double actual[1681],expected[1681];polar::MarkerMatch result{};
        auto status=polar::matchMarker(image.data(),w,h,marker.data(),mw,mh,tx,ty,actual,1681,result);
        assert(status!=polar::AlignmentStatus::InvalidInput&&status!=polar::AlignmentStatus::FlatMarker);
        reference(image,w,h,marker,mw,mh,tx,ty,expected);
        assert(std::memcmp(actual,expected,sizeof(actual))==0);
        if(status==polar::AlignmentStatus::Ok)++accepted;
        ++cases;
    }
    assert(accepted>0);
    std::printf("%d marker searches: all 1681 scores bit-identical; %d accepted\n",cases,accepted);
}
