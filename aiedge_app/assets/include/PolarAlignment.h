#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstddef>

namespace polar {
enum class AlignmentStatus { Ok, InvalidInput, FlatMarker, WeakMatch, Boundary, Spacing, Rotation, Confirmation, Geometry, Ambiguous };
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
            for(int row=0;row<mh;++row) {
                // Width is bounded by 4096 above: each row's squared/dot sum
                // is at most 4096*255*255 = 266342400, safely within int32.
                // Retain 64-bit totals for tall patches; integer sums are exact.
                int32_t rowSum=0,rowSquared=0,rowDot=0;
                for(int col=0;col<mw;++col) {
                    const int p=gray[(y+row)*width+x+col];
                    rowSum+=p; rowSquared+=p*p; rowDot+=p*marker[row*mw+col];
                }
                ps+=rowSum; pq+=rowSquared; dot+=rowDot;
            }
            const double pv=std::max(0.0,pq-double(ps)*ps/n);
            scores[k]=(dot-double(ts)*ps/n)/std::max(1e-9,std::sqrt(tv*pv));
        }
        if(scores[k]>scores[best]) best=k;
    }
    if(scores[best]<.8) return AlignmentStatus::WeakMatch;
    const int yi=best/41,xi=best%41;
    if(xi==0 || xi==40 || yi==0 || yi==40) return AlignmentStatus::Boundary;
    // A second separated peak can represent another copy of the same marking.
    // Exclude only the local peak neighborhood; do not refit to a runner-up.
    double runner=-1;
    for(int y=0;y<41;++y)for(int x=0;x<41;++x) {
        if(std::abs(x-xi)<=8 && std::abs(y-yi)<=8)continue;
        runner=std::max(runner,scores[y*41+x]);
    }
    // Provisional local-search margin; not an accuracy probability.
    if(scores[best]-runner<.05)return AlignmentStatus::Ambiguous;
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
    // Automatic correction is limited to a conservative small-motion envelope.
    // Larger rotations need a reference/calibration check: marker matches alone
    // did not protect dial recognition in the 10-degree full-frame stress test.
    constexpr double maximumRotationRadians=2.0*3.14159265358979323846/180.0;
    const double wrappedTheta=std::atan2(std::sin(theta),std::cos(theta));
    if(std::abs(wrappedTheta)>maximumRotationRadians+1e-12)return AlignmentStatus::Rotation;
    const double c=std::cos(theta),s=std::sin(theta);
    const double x=(a.foundX+b.foundX)/2,y=(a.foundY+b.foundY)/2;
    matrix[0]=c; matrix[1]=-s; matrix[2]=(a.targetX+b.targetX)/2-c*x+s*y;
    matrix[3]=s; matrix[4]=c; matrix[5]=(a.targetY+b.targetY)/2-s*x-c*y;
    return AlignmentStatus::Ok;
}
// The third observation verifies, but never refits, the two-marker correction.
// Failure leaves the caller's matrix untouched.
inline AlignmentStatus confirmedRegistration(const MarkerMatch& a,const MarkerMatch& b,
        const MarkerMatch& check,double maximumResidual,double* matrix) {
    if(!matrix || !std::isfinite(maximumResidual) || maximumResidual<=0)
        return AlignmentStatus::InvalidInput;
    const double values[]={check.targetX,check.targetY,check.foundX,check.foundY,check.correlation};
    for(double v:values)if(!std::isfinite(v))return AlignmentStatus::InvalidInput;
    if(check.correlation<.8)return AlignmentStatus::WeakMatch;
    double candidate[6];auto status=registration(a,b,candidate);
    if(status!=AlignmentStatus::Ok)return status;
    const double ab=std::hypot(b.targetX-a.targetX,b.targetY-a.targetY);
    const double ac=std::hypot(check.targetX-a.targetX,check.targetY-a.targetY);
    const double bc=std::hypot(check.targetX-b.targetX,check.targetY-b.targetY);
    const double longest=std::max(ab,std::max(ac,bc));
    const double area2=std::abs((b.targetX-a.targetX)*(check.targetY-a.targetY)-
                              (b.targetY-a.targetY)*(check.targetX-a.targetX));
    if(std::min(ab,std::min(ac,bc))<1 || area2/(longest*longest)<.1)
        return AlignmentStatus::Geometry;
    const double x=candidate[0]*check.foundX+candidate[1]*check.foundY+candidate[2];
    const double y=candidate[3]*check.foundX+candidate[4]*check.foundY+candidate[5];
    if(std::hypot(x-check.targetX,y-check.targetY)>maximumResidual)
        return AlignmentStatus::Confirmation;
    std::copy(candidate,candidate+6,matrix);
    return AlignmentStatus::Ok;
}

}
