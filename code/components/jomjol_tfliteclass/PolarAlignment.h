#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstddef>

namespace polar {
enum class AlignmentStatus { Ok, InvalidInput, FlatMarker, WeakMatch, Boundary, Spacing };
struct MarkerMatch { double targetX, targetY, foundX, foundY, correlation; };
inline double subpixel(double left,double middle,double right) {
    const double denominator=left-2*middle+right;
    if(denominator>=-1e-9) return 0;
    return std::max(-.5,std::min(.5,.5*(left-right)/denominator));
}
// Fixed +/-20 pixel search. Caller supplies 1681 double scratch values.
inline AlignmentStatus matchMarker(const uint8_t* gray,int width,int height,
        const uint8_t* marker,int mw,int mh,int tx,int ty,
        double* scores,size_t capacity,MarkerMatch& result) {
    if(!gray || !marker || !scores || capacity<1681 || width<1 || height<1 ||
       width>4096 || height>4096 || mw<1 || mh<1 || mw>width || mh>height ||
       tx<0 || ty<0 || tx>width-mw || ty>height-mh) return AlignmentStatus::InvalidInput;
    int64_t ts=0,tq=0;
    const double n=mw*mh;
    for(int i=0;i<mw*mh;++i) { ts+=marker[i]; tq+=int(marker[i])*marker[i]; }
    const double tv=std::max(0.0,tq-double(ts)*ts/n);
    if(tv<1) return AlignmentStatus::FlatMarker;
    int best=0;
    for(int dy=-20;dy<=20;++dy) for(int dx=-20;dx<=20;++dx) {
        const int k=(dy+20)*41+dx+20,x=tx+dx,y=ty+dy;
        scores[k]=-1;
        if(x>=0 && y>=0 && x+mw<=width && y+mh<=height) {
            int64_t ps=0,pq=0,dot=0;
            for(int row=0;row<mh;++row) for(int col=0;col<mw;++col) {
                const int p=gray[(y+row)*width+x+col];
                ps+=p; pq+=p*p; dot+=p*marker[row*mw+col];
            }
            const double pv=std::max(0.0,pq-double(ps)*ps/n);
            scores[k]=(dot-double(ts)*ps/n)/std::max(1e-9,std::sqrt(tv*pv));
        }
        if(scores[k]>scores[best]) best=k;
    }
    if(scores[best]<.8) return AlignmentStatus::WeakMatch;
    const int yi=best/41,xi=best%41;
    if(xi==0 || xi==40 || yi==0 || yi==40) return AlignmentStatus::Boundary;
    MarkerMatch next;
    next.targetX=tx+mw/2.0; next.targetY=ty+mh/2.0;
    next.foundX=next.targetX+xi-20+subpixel(scores[best-1],scores[best],scores[best+1]);
    next.foundY=next.targetY+yi-20+subpixel(scores[best-41],scores[best],scores[best+41]);
    next.correlation=scores[best]; result=next;
    return AlignmentStatus::Ok;
}
// Source-to-reference affine matrix, row-major 2x3, with no scale correction.
inline AlignmentStatus registration(const MarkerMatch& a,const MarkerMatch& b,double* matrix) {
    if(!matrix) return AlignmentStatus::InvalidInput;
    const double vals[]={a.targetX,a.targetY,a.foundX,a.foundY,a.correlation,
                         b.targetX,b.targetY,b.foundX,b.foundY,b.correlation};
    for(double v:vals) if(!std::isfinite(v)) return AlignmentStatus::InvalidInput;
    if(a.correlation<.8 || b.correlation<.8) return AlignmentStatus::WeakMatch;
    const double ux=b.foundX-a.foundX,uy=b.foundY-a.foundY;
    const double vx=b.targetX-a.targetX,vy=b.targetY-a.targetY;
    const double destination=std::hypot(vx,vy);
    if(destination<1e-9) return AlignmentStatus::InvalidInput;
    if(std::abs(std::hypot(ux,uy)/destination-1)>.02) return AlignmentStatus::Spacing;
    const double theta=std::atan2(vy,vx)-std::atan2(uy,ux);
    const double c=std::cos(theta),s=std::sin(theta);
    const double x=(a.foundX+b.foundX)/2,y=(a.foundY+b.foundY)/2;
    matrix[0]=c; matrix[1]=-s; matrix[2]=(a.targetX+b.targetX)/2-c*x+s*y;
    matrix[3]=s; matrix[4]=c; matrix[5]=(a.targetY+b.targetY)/2-s*x-c*y;
    return AlignmentStatus::Ok;
}
}
