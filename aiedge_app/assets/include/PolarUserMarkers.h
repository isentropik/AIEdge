#pragma once
#include "PolarAlignment.h"
#include "PolarMarkerCalibration.h"
#include <cstring>
namespace polar {
struct UserMarkerBox {int x,y,w,h;};
// Allocated in PSRAM by the device owner, never on a task stack.
struct UserMarkers {
 uint8_t pixels[3][128*128];
 MarkerCalibration calibration{};
 bool ready=false;
};
inline bool markerBoxesValid(const UserMarkerBox* boxes,int count){
 if(!boxes||count!=3)return false;
 for(int i=0;i<3;++i){const auto& a=boxes[i];
  if(a.w<8||a.h<8||a.w>128||a.h>128||a.x<0||a.y<0||a.x>640-a.w||a.y>480-a.h)return false;
  for(int j=0;j<i;++j){const auto& b=boxes[j];
   if(a.x<b.x+b.w&&b.x<a.x+a.w&&a.y<b.y+b.h&&b.y<a.y+a.h)return false;
  }
 }
 MarkerMatch m[3];for(int i=0;i<3;++i)m[i]={boxes[i].x+boxes[i].w/2.0,boxes[i].y+boxes[i].h/2.0,boxes[i].x+boxes[i].w/2.0,boxes[i].y+boxes[i].h/2.0,1};
 double matrix[6];return confirmedRegistration(m[0],m[1],m[2],3,matrix)==AlignmentStatus::Ok;
}
// inverse maps canonical pixels to the saved reference. Invert it to keep the
// model's reference plane and fixed needle pivots unchanged.
inline bool makeUserMarkers(const uint8_t* referenceGray,const UserMarkerBox* boxes,
                            const double* inverse,UserMarkers& out){
 out.ready=false;
 if(!referenceGray||!inverse||!markerBoxesValid(boxes,3))return false;
 for(int i=0;i<6;++i)if(!std::isfinite(inverse[i]))return false;
 const double det=inverse[0]*inverse[4]-inverse[1]*inverse[3];
 if(std::abs(det-1)>0.001)return false;
 for(int i=0;i<3;++i){const auto& b=boxes[i];
  for(int y=0;y<b.h;++y)std::memcpy(out.pixels[i]+y*b.w,referenceGray+(b.y+y)*640+b.x,b.w);
  const double x=b.x+b.w/2.0-inverse[2],y=b.y+b.h/2.0-inverse[5];
  out.calibration.markers[i]={out.pixels[i],size_t(b.w*b.h),b.w,b.h,b.x,b.y,
    (inverse[4]*x-inverse[1]*y)/det,(-inverse[3]*x+inverse[0]*y)/det};
 }
 out.ready=validMarkerCalibration(out.calibration);return out.ready;
}
}
