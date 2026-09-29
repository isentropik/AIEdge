#pragma once
// Bounded recovery for a translated view. Fine search and registration guards remain mandatory.
#include "PolarAlignment.h"
#include "PolarCalibration.h"
#include "PolarAlignmentCheck.h"
#include "PolarMarkerCalibration.h"
namespace polar {
inline AlignmentStatus matchMarkerCoarse(const uint8_t* full,const uint8_t* half,
        const uint8_t* marker,const int* spec,double* scores,polar::MarkerMatch& result) {
    if(!full||!half||!marker||!spec||!scores)return AlignmentStatus::InvalidInput;
    const int w=spec[0],h=spec[1],tx=spec[2],ty=spec[3];
    if(w<2||h<2||w>128||h>128||tx<0||ty<0||tx>640-w||ty>480-h)return AlignmentStatus::InvalidInput;
    const int mw=w/2,mh=h/2;
    uint8_t small[64*64];
    for(int y=0;y<mh;++y)for(int x=0;x<mw;++x)
        small[y*mw+x]=(int(marker[2*y*w+2*x])+marker[2*y*w+2*x+1]+
                          marker[(2*y+1)*w+2*x]+marker[(2*y+1)*w+2*x+1])/4;
    polar::MarkerMatch coarse;
    auto status=polar::matchMarker(half,320,240,small,mw,mh,tx/2,ty/2,scores,1681,coarse);
    if(status!=polar::AlignmentStatus::Ok)return status;
    const int cx=tx+int(std::round(2*(coarse.foundX-coarse.targetX)));
    const int cy=ty+int(std::round(2*(coarse.foundY-coarse.targetY)));
    if(cx<0||cy<0||cx+w>640||cy+h>480)return polar::AlignmentStatus::Boundary;
    polar::MarkerMatch fine;
    status=polar::matchMarker(full,640,480,marker,w,h,cx,cy,scores,1681,fine);
    if(status!=polar::AlignmentStatus::Ok)return status;
    fine.targetX=tx+w/2.0;fine.targetY=ty+h/2.0;
    if(std::abs(fine.foundX-fine.targetX)>40 || std::abs(fine.foundY-fine.targetY)>40)
        return polar::AlignmentStatus::Boundary;
    result=fine;return polar::AlignmentStatus::Ok;
}
inline AlignmentStatus alignFrameCoarse(const uint8_t* gray,uint8_t* half,size_t halfCapacity,double* scores,double* inverse,
        const MarkerCalibration& calibration=frozenMarkerCalibration()) {
    if(!gray||!half||halfCapacity<320*240||!scores||!inverse||!validMarkerCalibration(calibration))return AlignmentStatus::InvalidInput;
    for(int y=0;y<240;++y)for(int x=0;x<320;++x)
        half[y*320+x]=(int(gray[2*y*640+2*x])+gray[2*y*640+2*x+1]+
                      gray[(2*y+1)*640+2*x]+gray[(2*y+1)*640+2*x+1])/4;
    polar::MarkerMatch matches[3];
    for(int i=0;i<3;++i){
        const auto& m=calibration.markers[i];
        const int spec[]={m.width,m.height,m.searchX,m.searchY};
        auto status=matchMarkerCoarse(gray,half,m.pixels,spec,scores,matches[i]);
        if(status!=polar::AlignmentStatus::Ok)return status;
        matches[i].targetX=m.targetX;matches[i].targetY=m.targetY;
    }
    double forward[6];auto status=polar::confirmedRegistration(matches[0],matches[1],matches[2],3.0,forward);
    if(status!=polar::AlignmentStatus::Ok)return status;
    const double determinant=forward[0]*forward[4]-forward[1]*forward[3];
    inverse[0]=forward[4]/determinant;inverse[1]=-forward[1]/determinant;
    inverse[3]=-forward[3]/determinant;inverse[4]=forward[0]/determinant;
    inverse[2]=-(inverse[0]*forward[2]+inverse[1]*forward[5]);
    inverse[5]=-(inverse[3]*forward[2]+inverse[4]*forward[5]);
    return polar::AlignmentStatus::Ok;
}
}
