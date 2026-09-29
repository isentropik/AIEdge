#pragma once
#include <cstddef>
#include <cstdint>
#include <algorithm>

namespace polar {
// RGB-to-luma fixed-point coefficients used by the frozen Pillow pipeline.
inline bool grayscale(const uint8_t* rgb, size_t pixels, uint8_t* gray) {
    if (!rgb || !gray || !pixels) return false;
    for(size_t i=0;i<pixels;++i)
        gray[i]=(19595u*rgb[3*i]+38470u*rgb[3*i+1]+7471u*rgb[3*i+2]+32768u)>>16;
    return true;
}

// Fixed radius 0.4, three fractional box passes per axis. Two distinct,
// caller-owned width*height buffers are required; output is always in gray.
// Matches the frozen pipeline's per-pass uint8 rounding and edge replication.
inline bool blur04(uint8_t* gray, uint8_t* temporary, int width, int height) {
    if(!gray || !temporary || gray==temporary || width<1 || height<1) return false;
    const float variance=0.4f*0.4f/3;
    const float radius=(-3*variance)/(6*(variance-1));
    const uint32_t center=static_cast<uint32_t>(16777216u/(radius*2+1));
    const uint32_t side=(16777216u-center)/2;
    uint8_t* source=gray;
    uint8_t* destination=temporary;
    for(int axis=0;axis<2;++axis) {
        for(int pass=0;pass<3;++pass) {
            for(int y=0;y<height;++y) for(int x=0;x<width;++x) {
                const int left=axis==0 ? y*width+std::max(0,x-1) : std::max(0,y-1)*width+x;
                const int right=axis==0 ? y*width+std::min(width-1,x+1) : std::min(height-1,y+1)*width+x;
                const int i=y*width+x;
                const uint32_t sum=source[i]*center+(source[left]+source[right])*side;
                destination[i]=(sum+8388608u)>>24;
            }
            std::swap(source,destination);
        }
    }
    return true;
}
}
