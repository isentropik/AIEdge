#pragma once
#include "PolarAlignment.h"
#include "PolarImage.h"
#include "PolarWarp.h"
#include "PolarFeatures.h"
#include "PolarCalibration.h"
#include "PolarAlignmentCheck.h"
#include "PolarVisibility.h"
#include "PolarProfile.h"

namespace polar {
// Allocate once in PSRAM/on heap, not on the task stack. Six dials reuse buffers.
struct PipelineScratch {
    uint8_t fullGray[640*480];
    uint8_t crop[148*148*3],gray[148*148],temporary[148*148];
    double scores[1681],coordinates[14400],samples[7200],sorted[360];
    int8_t features[384*40];
    double visibilityScore;
};
inline AlignmentStatus alignFrame(const uint8_t* rgb,int width,int height,
                                  PipelineScratch& scratch,double* inverse) {
    if(!rgb || !inverse || width!=calibratedWidth || height!=calibratedHeight)
        return AlignmentStatus::InvalidInput;
    grayscale(rgb,width*height,scratch.fullGray);
    MarkerMatch a,b,check;
    auto status=matchMarker(scratch.fullGray,width,height,marker0,marker0Spec[0],marker0Spec[1],marker0Spec[2],marker0Spec[3],scratch.scores,1681,a);
    if(status!=AlignmentStatus::Ok)return status;
    status=matchMarker(scratch.fullGray,width,height,marker1,marker1Spec[0],marker1Spec[1],marker1Spec[2],marker1Spec[3],scratch.scores,1681,b);
    if(status!=AlignmentStatus::Ok)return status;
    status=matchMarker(scratch.fullGray,width,height,checkMarker,checkMarkerSpec[0],checkMarkerSpec[1],checkMarkerSpec[2],checkMarkerSpec[3],scratch.scores,1681,check);
    if(status!=AlignmentStatus::Ok)return status;
    // Provisional three-pixel consistency limit; independent real captures still required.
    double forward[6];status=confirmedRegistration(a,b,check,3.0,forward);
    if(status!=AlignmentStatus::Ok)return status;
    const double determinant=forward[0]*forward[4]-forward[1]*forward[3];
    inverse[0]=forward[4]/determinant;inverse[1]=-forward[1]/determinant;
    inverse[3]=-forward[3]/determinant;inverse[4]=forward[0]/determinant;
    inverse[2]=-(inverse[0]*forward[2]+inverse[1]*forward[5]);
    inverse[5]=-(inverse[3]*forward[2]+inverse[4]*forward[5]);
    return AlignmentStatus::Ok;
}
inline bool prepareDial(const uint8_t* rgb,const double* inverse,int index,PipelineScratch& scratch,
                        DialProfile* profile=nullptr,int64_t (*clock)()=nullptr, bool sparse=false) {
    if(profile)*profile=DialProfile{};
    if(index<0 || index>=6)return false;
    DialProfileTimer timing(profile,clock);
    const auto& d=dials[index];
    if(!warpCrop(rgb,640,480,inverse,d.x,d.y,d.w,d.h,scratch.crop,sparse))return false;
    timing.next();
    if(!grayscale(scratch.crop,d.w*d.h,scratch.gray))return false;
    if(!contrastValid(scratch.gray,d.w*d.h))return false;
    timing.next();
    if(!visibility(scratch.gray,d,scratch.samples,scratch.sorted,scratch.visibilityScore) ||
       scratch.visibilityScore<visibilityThreshold)return false;
    timing.next();
    if(!blur04(scratch.gray,scratch.temporary,d.w,d.h))return false;
    timing.next();
    const double pi=3.14159265358979323846;
    double radii[20];
    for(int r=0;r<20;++r)radii[r]=.32+(.94-.32)*r/19;
    for(int angle=0;angle<360;++angle) {
        const double a=angle*2*pi/360;
        for(int r=0;r<20;++r) {
            const double radius=radii[r];
            const double x=d.pivot[0]+std::sin(a)*radius,y=d.pivot[1]-std::cos(a)*radius;
            const double z=d.inverse[6]*x+d.inverse[7]*y+d.inverse[8];
            if(!std::isfinite(z) || std::abs(z)<1e-12)return false;
            const int k=2*(angle*20+r);
            scratch.coordinates[k]=(d.inverse[0]*x+d.inverse[1]*y+d.inverse[2])/z;
            scratch.coordinates[k+1]=(d.inverse[3]*x+d.inverse[4]*y+d.inverse[5])/z;
        }
    }
    timing.next();
    return features(scratch.gray,d.w,d.h,scratch.coordinates,scratch.samples,scratch.sorted,scratch.features,384*40);
}
}
