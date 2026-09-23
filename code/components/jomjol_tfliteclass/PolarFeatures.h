#pragma once
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>

namespace polar {
// Input is Pillow-compatible grayscale after the frozen radius-0.4 blur.
// coordinates contains 360*20 pairs in original crop pixel coordinates.
// scratch: 7200 doubles; sorted: 360 doubles; output: 384*40 int8 values.
// Buffers are supplied by caller so ESP32 can use PSRAM rather than stack.
inline bool features(const uint8_t* gray, int width, int height,
                     const double* coordinates, double* scratch, double* sorted,
                     int8_t* output, size_t count) {
    if (!gray || !coordinates || !scratch || !sorted || !output ||
        width < 2 || height < 2 || count != 384*40) return false;
    for (int i=0; i<7200; ++i) {
        double x=coordinates[2*i], y=coordinates[2*i+1];
        if (!std::isfinite(x) || !std::isfinite(y)) return false;
        x=std::max(0.0,std::min(x,width-1.001));
        y=std::max(0.0,std::min(y,height-1.001));
        const int ix=static_cast<int>(x), iy=static_cast<int>(y);
        const double fx=x-ix, fy=y-iy;
        scratch[i]=gray[iy*width+ix]*(1-fx)*(1-fy) +
            gray[iy*width+ix+1]*fx*(1-fy) +
            gray[(iy+1)*width+ix]*(1-fx)*fy +
            gray[(iy+1)*width+ix+1]*fx*fy;
    }
    for (int r=0; r<20; ++r) {
        for (int a=0; a<360; ++a) sorted[a]=scratch[a*20+r];
        std::sort(sorted,sorted+360);
        // NumPy percentile(75): (360-1)*0.75 = 269.25.
        const double background=sorted[269]*.75+sorted[270]*.25;
        for (int a=0; a<384; ++a) {
            const double sample=scratch[((a+348)%360)*20+r];
            const float channels[2]={static_cast<float>((background-sample)/128.0),
                                     static_cast<float>(sample/255.0)};
            for (int c=0; c<2; ++c) {
                const float rounded=std::nearbyint(channels[c]/0.006855103187263012f)-53;
                output[a*40+c*20+r]=static_cast<int8_t>(std::max(-128.0f,std::min(127.0f,rounded)));
            }
        }
    }
    return true;
}
}
