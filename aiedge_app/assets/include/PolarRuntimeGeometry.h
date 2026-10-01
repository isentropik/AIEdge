#pragma once
#include "PolarCalibration.h"
#include <algorithm>
#include <cmath>

namespace polar {
// Candidate geometry only. Validation does not approve a new camera pose,
// registration template, model or accounting continuity.
enum class GeometryStatus { Ok, Frame, Crop, Capacity, NonFinite, Singular,
                            Horizon, SamplingBounds };
inline const char* geometryStatusName(GeometryStatus value) {
    switch(value) {
    case GeometryStatus::Ok:return "ok";
    case GeometryStatus::Frame:return "frame_dimensions_invalid";
    case GeometryStatus::Crop:return "crop_outside_frame";
    case GeometryStatus::Capacity:return "crop_exceeds_workspace";
    case GeometryStatus::NonFinite:return "geometry_not_finite";
    case GeometryStatus::Singular:return "geometry_singular";
    case GeometryStatus::Horizon:return "projection_crosses_sampling_region";
    case GeometryStatus::SamplingBounds:return "crop_cuts_sampling_region";
    }
    return "geometry_invalid";
}
inline bool finiteHomography(const double* matrix) {
    if(!matrix)return false;
    for(int i=0;i<9;++i)if(!std::isfinite(matrix[i]))return false;
    return true;
}
inline bool nonsingularHomography(const double* matrix) {
    if(!finiteHomography(matrix))return false;
    double scale=0;
    for(int i=0;i<9;++i)scale=std::max(scale,std::abs(matrix[i]));
    if(scale==0)return false;
    double m[9];for(int i=0;i<9;++i)m[i]=matrix[i]/scale;
    const double det=m[0]*(m[4]*m[8]-m[5]*m[7])-
        m[1]*(m[3]*m[8]-m[5]*m[6])+m[2]*(m[3]*m[7]-m[4]*m[6]);
    return std::isfinite(det)&&std::abs(det)>1e-12;
}
inline void multiplyHomographies(const double* a,const double* b,double* result) {
    double next[9]{};
    for(int r=0;r<3;++r)for(int c=0;c<3;++c)for(int k=0;k<3;++k)
        next[3*r+c]+=a[3*r+k]*b[3*k+c];
    std::copy(next,next+9,result);
}
// Run when preparing a profile, not once per frame. Bounds include a two-pixel
// margin for filtering and bilinear interpolation; no coordinate clamping is
// allowed to disguise a cropped-out part of the calibrated sampling region.
inline GeometryStatus validateDialGeometry(const DialGeometry& d,int width=640,int height=480) {
    if(width!=calibratedWidth||height!=calibratedHeight)return GeometryStatus::Frame;
    if(d.w<2||d.h<2||d.x<0||d.y<0||d.w>width||d.h>height||
       d.x>width-d.w||d.y>height-d.h)return GeometryStatus::Crop;
    if(d.w>148||d.h>148)return GeometryStatus::Capacity;
    if(!finiteHomography(d.inverse)||!std::isfinite(d.pivot[0])||
       !std::isfinite(d.pivot[1]))return GeometryStatus::NonFinite;
    if(!nonsingularHomography(d.inverse))return GeometryStatus::Singular;
    // Linear projective denominator over the entire radius-.94 disk. Checking
    // only sampled points could miss a horizon between two adjacent rays.
    const double center=d.inverse[6]*d.pivot[0]+d.inverse[7]*d.pivot[1]+d.inverse[8];
    const double spread=.94*std::hypot(d.inverse[6],d.inverse[7]);
    if(!std::isfinite(center)||!std::isfinite(spread)||std::abs(center)<=spread+1e-12)
        return GeometryStatus::Horizon;
    const double pi=3.14159265358979323846;
    for(int angle=0;angle<360;++angle)for(int ring=0;ring<32;++ring) {
        // Exact feature radii and exact visibility radii, both about the fixed
        // needle pivot (which need not equal the printed dial's center).
        const double radius=ring<20 ? .32+(.94-.32)*ring/19 : .35+(.60-.35)*(ring-20)/11;
        const double a=angle*2*pi/360;
        const double u=d.pivot[0]+std::sin(a)*radius,v=d.pivot[1]-std::cos(a)*radius;
        const double z=d.inverse[6]*u+d.inverse[7]*v+d.inverse[8];
        const double x=(d.inverse[0]*u+d.inverse[1]*v+d.inverse[2])/z;
        const double y=(d.inverse[3]*u+d.inverse[4]*v+d.inverse[5])/z;
        if(!std::isfinite(x)||!std::isfinite(y))return GeometryStatus::NonFinite;
        if(x<2||y<2||x>d.w-3.001||y>d.h-3.001)return GeometryStatus::SamplingBounds;
    }
    return GeometryStatus::Ok;
}
// Transfer a reviewed dial plane into another reference frame. The caller must
// independently validate old-reference -> new-reference registration. This does
// not estimate it from a crop box, recenter the needle, or accept it for use.
// Leave output unchanged on failure so a partial candidate cannot escape.
inline GeometryStatus transportDialGeometry(const DialGeometry& source,const double* reference,
                                             int x,int y,int width,int height,DialGeometry& output) {
    auto status=validateDialGeometry(source);if(status!=GeometryStatus::Ok)return status;
    if(!finiteHomography(reference))return GeometryStatus::NonFinite;
    if(!nonsingularHomography(reference))return GeometryStatus::Singular;
    const double oldCropToFrame[9]={1,0,double(source.x),0,1,double(source.y),0,0,1};
    const double frameToNewCrop[9]={1,0,-double(x),0,1,-double(y),0,0,1};
    double global[9],moved[9];
    multiplyHomographies(oldCropToFrame,source.inverse,global);
    multiplyHomographies(reference,global,moved);
    DialGeometry next=source;next.x=x;next.y=y;next.w=width;next.h=height;
    multiplyHomographies(frameToNewCrop,moved,next.inverse);
    status=validateDialGeometry(next);if(status==GeometryStatus::Ok)output=next;
    return status;
}
inline GeometryStatus rebaseDialGeometry(const DialGeometry& source,int x,int y,int width,int height,
                                         DialGeometry& output) {
    const double identity[9]={1,0,0,0,1,0,0,0,1};
    return transportDialGeometry(source,identity,x,y,width,height,output);
}
// Own a validated copy: edits to the candidate cannot invalidate active bounds.
// This validates numerical geometry only, not reference/model compatibility.
class ValidatedDialGeometry {
    DialGeometry geometry;
    GeometryStatus result;
    int phaseX=0,phaseY=0;
public:
    explicit ValidatedDialGeometry(const DialGeometry& candidate)
        :geometry(candidate),result(validateDialGeometry(candidate)){}
    // The anchor is the reviewed sampling origin in the SAME reference frame.
    // A new camera/reference transform still requires separate validation.
    ValidatedDialGeometry(const DialGeometry& candidate,int anchorX,int anchorY)
        :geometry(candidate),result(validateDialGeometry(candidate)),
         phaseX((anchorX&1)^(candidate.x&1)),phaseY((anchorY&1)^(candidate.y&1)){}
    int samplingPhaseX() const{return phaseX;}
    int samplingPhaseY() const{return phaseY;}
    GeometryStatus status() const{return result;}
    const DialGeometry* get() const{return result==GeometryStatus::Ok?&geometry:nullptr;}
};

}
