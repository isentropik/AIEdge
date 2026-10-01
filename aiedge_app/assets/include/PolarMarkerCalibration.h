#pragma once
#include "PolarCalibration.h"
#include "PolarAlignmentCheck.h"
#include <cmath>
namespace polar {
// A borrowed view into an immutable profile. Its owner must keep all template
// bytes alive for the entire frame. Search positions and canonical centers are
// distinct: changing a search window must not silently change registration.
struct MarkerTemplate {
 const uint8_t* pixels;
 size_t bytes;
 int width,height,searchX,searchY;
 double targetX,targetY;
};
struct MarkerCalibration {MarkerTemplate markers[3];};
inline bool validMarkerCalibration(const MarkerCalibration& profile){
 for(const auto& m:profile.markers){
  if(!m.pixels||m.width<2||m.height<2||m.width>128||m.height>128||
     m.bytes!=size_t(m.width*m.height)||m.searchX<0||m.searchY<0||
     m.searchX>640-m.width||m.searchY>480-m.height||
     !std::isfinite(m.targetX)||!std::isfinite(m.targetY)||
     m.targetX<m.width/2.0||m.targetY<m.height/2.0||
     m.targetX>640-m.width/2.0||m.targetY>480-m.height/2.0)return false;
 }
 return true;
}
inline const MarkerCalibration& frozenMarkerCalibration(){
 static const MarkerCalibration profile{{
  {marker0,sizeof(marker0),marker0Spec[0],marker0Spec[1],marker0Spec[2],marker0Spec[3],marker0Spec[2]+marker0Spec[0]/2.0,marker0Spec[3]+marker0Spec[1]/2.0},
  {marker1,sizeof(marker1),marker1Spec[0],marker1Spec[1],marker1Spec[2],marker1Spec[3],marker1Spec[2]+marker1Spec[0]/2.0,marker1Spec[3]+marker1Spec[1]/2.0},
  {checkMarker,sizeof(checkMarker),checkMarkerSpec[0],checkMarkerSpec[1],checkMarkerSpec[2],checkMarkerSpec[3],checkMarkerSpec[2]+checkMarkerSpec[0]/2.0,checkMarkerSpec[3]+checkMarkerSpec[1]/2.0}
 }};
 return profile;
}
}
