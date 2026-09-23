#pragma once
#include "PolarCalibration.h"
#include "PolarPercentile.h"
#include <algorithm>
#include <cmath>
#include <cstdint>

namespace polar {
constexpr double visibilityThreshold=44.7977398243656;
inline double histogramPercentile(const int* counts,int pixels,double fraction) {
    const double rank=(pixels-1)*fraction;
    const int lo=static_cast<int>(rank),hi=static_cast<int>(std::ceil(rank));
    int seen=0,lower=0,upper=0;
    for(int i=0;i<256;++i) {
        const int next=seen+counts[i];
        if(seen<=lo && lo<next)lower=i;
        if(seen<=hi && hi<next){upper=i;break;}
        seen=next;
    }
    return lower+(upper-lower)*(rank-lo);
}
inline bool contrastValid(const uint8_t* gray,int count) {
    if(!gray || count<1)return false;
    int histogram[256]={0};
    for(int i=0;i<count;++i)++histogram[gray[i]];
    return histogramPercentile(histogram,count,.9)-histogramPercentile(histogram,count,.1)>=15;
}
// Uses unblurred grayscale, 4320 sample scratch doubles and 360 sort doubles.
inline bool visibility(const uint8_t* gray,const DialGeometry& d,double* samples,
                       double* sorted,double& score) {
    if(!gray || !samples || !sorted || d.w<2 || d.h<2)return false;
    const double pi=3.14159265358979323846;
    for(int a=0;a<360;++a)for(int r=0;r<12;++r) {
        const double angle=a*pi/180,radius=.35+(.60-.35)*r/11;
        const double u=d.pivot[0]+std::sin(angle)*radius,v=d.pivot[1]-std::cos(angle)*radius;
        const double z=d.inverse[6]*u+d.inverse[7]*v+d.inverse[8];
        if(!std::isfinite(z) || std::abs(z)<1e-12)return false;
        double x=(d.inverse[0]*u+d.inverse[1]*v+d.inverse[2])/z;
        double y=(d.inverse[3]*u+d.inverse[4]*v+d.inverse[5])/z;
        if(!std::isfinite(x) || !std::isfinite(y))return false;
        x=std::max(0.0,std::min(x,d.w-1.001));y=std::max(0.0,std::min(y,d.h-1.001));
        const int ix=static_cast<int>(x),iy=static_cast<int>(y);
        const double fx=x-ix,fy=y-iy;
        samples[a*12+r]=gray[iy*d.w+ix]*(1-fx)*(1-fy)+gray[iy*d.w+ix+1]*fx*(1-fy)+
            gray[(iy+1)*d.w+ix]*(1-fx)*fy+gray[(iy+1)*d.w+ix+1]*fx*fy;
    }
    double background[12];
    for(int r=0;r<12;++r) {
        for(int a=0;a<360;++a)sorted[a]=samples[a*12+r];
        selectPercentile75(sorted);background[r]=sorted[269]*.75+sorted[270]*.25;
    }
    double best=-1e9;
    for(int a=0;a<360;++a) {
        for(int r=0;r<12;++r)sorted[r]=background[r]-samples[a*12+r];
        std::sort(sorted,sorted+12);
        best=std::max(best,sorted[2]*.25+sorted[3]*.75);
    }
    score=best;return true;
}
}
