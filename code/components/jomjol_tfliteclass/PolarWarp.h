#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>

// Compatible with Pillow 12.3.0 Geometry.c affine bicubic sampling.
// See third-party-notices/Pillow-LICENSE.txt.
namespace polar {
inline double cubic(double a,double b,double c,double d,double fraction) {
    return b+fraction*((-a+c)+fraction*(2*(a-b)+c-d+fraction*(-a+b-c+d)));
}
// Sample a reference-frame ROI directly; avoid allocating a second full RGB frame.
// inverse is reference-to-source affine (2x3), not the marker result's forward matrix.
inline bool warpCrop(const uint8_t* source,int width,int height,const double* inverse,
                     int left,int top,int cropWidth,int cropHeight,uint8_t* output) {
    if(!source || !inverse || !output || source==output || width<1 || height<1 ||
       width>4096 || height>4096 || left<0 || top<0 || cropWidth<1 || cropHeight<1 ||
       cropWidth>width || cropHeight>height || left>width-cropWidth || top>height-cropHeight) return false;
    for(int i=0;i<6;++i) if(!std::isfinite(inverse[i])) return false;
    for(int row=0;row<cropHeight;++row) for(int col=0;col<cropWidth;++col) {
        const double x=left+col+.5,y=top+row+.5;
        double sx=inverse[0]*x+inverse[1]*y+inverse[2];
        double sy=inverse[3]*x+inverse[4]*y+inverse[5];
        uint8_t* pixel=output+3*(row*cropWidth+col);
        if(!std::isfinite(sx) || !std::isfinite(sy)) return false;
        if(sx<0 || sy<0 || sx>=width || sy>=height) {pixel[0]=pixel[1]=pixel[2]=0;continue;}
        sx-=.5;sy-=.5;
        const int ix=static_cast<int>(std::floor(sx)),iy=static_cast<int>(std::floor(sy));
        const double dx=sx-ix,dy=sy-iy;
        for(int channel=0;channel<3;++channel) {
            double rows[4];
            for(int r=0;r<4;++r) {
                const int yy=std::max(0,std::min(height-1,iy-1+r));
                double taps[4];
                for(int c=0;c<4;++c) {
                    const int xx=std::max(0,std::min(width-1,ix-1+c));
                    taps[c]=source[3*(yy*width+xx)+channel];
                }
                rows[r]=cubic(taps[0],taps[1],taps[2],taps[3],dx);
            }
            const double v=cubic(rows[0],rows[1],rows[2],rows[3],dy);
            pixel[channel]=static_cast<uint8_t>(std::max(0.0,std::min(255.0,v)));
        }
    }
    return true;
}
}
