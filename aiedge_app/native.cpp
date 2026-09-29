#include <cstdint>
#include <cstddef>
#include <cstring>
#include <memory>
#include <vector>
#include "PolarUserMarkers.h"
#include "PolarPipeline.h"
#include "PolarDecoder.h"
#include "RevolutionReading.h"
#ifdef _WIN32
#define API extern "C" __declspec(dllexport)
#else
#define API extern "C" __attribute__((visibility("default")))
#endif
// ABI 2 retains the frozen replay path and adds owned runtime calibration.
API int aiedge_abi() { return 2; }
API int aiedge_prepare(const uint8_t* rgb,size_t bytes,int sparse,int8_t* output,size_t capacity,int* states,double* visibility) {
 if(!rgb||bytes!=640*480*3||!output||capacity!=6*384*40||!states||!visibility||(sparse!=0&&sparse!=1))return -1;
 std::memset(output,0,capacity);
 for(int i=0;i<6;++i){states[i]=0;visibility[i]=-1;}
 try {
  std::unique_ptr<polar::PipelineScratch> scratch(new polar::PipelineScratch);
  double inverse[6];
  if(polar::alignFrame(rgb,640,480,*scratch,inverse)!=polar::AlignmentStatus::Ok)return -2;
  for(int i=0;i<6;++i){
   const bool accepted=polar::prepareDial(rgb,inverse,i,*scratch,nullptr,nullptr,sparse!=0);
   states[i]=static_cast<int>(scratch->preparationStatus);visibility[i]=scratch->visibilityScore;
   if(accepted)std::memcpy(output+i*384*40,scratch->features,384*40);
  }
  return 0;
 } catch(...) {return -3;}
}
API const char* aiedge_preparation_status(int value) {
 if(value<0||value>static_cast<int>(polar::PreparationStatus::Ok))return "invalid_status";
 return polar::preparationStatusName(static_cast<polar::PreparationStatus>(value));
}
API int aiedge_decode(const int8_t* scores,size_t count,int ccw,float* value) {
 if(!scores||count!=360||!value||(ccw!=0&&ccw!=1))return -1;
 return polar::decode(scores,count,ccw!=0,*value)?0:-2;
}

struct RuntimeMarker {
 const uint8_t* pixels; size_t bytes;
 int x,y,w,h; double targetX,targetY;
};
struct RuntimeDial {
 int x,y,w,h,anchorX,anchorY;
 double inverse[9],pivot[2];
};
struct RuntimeProfile {
 std::vector<uint8_t> pixels[3];
 polar::MarkerCalibration markers{};
 std::vector<polar::ValidatedDialGeometry> dials;
};
// The handle owns all bytes and validated geometry. Caller buffers may be released
// after creation. No partial candidate replaces an existing handle.
API void* aiedge_profile_create(const RuntimeMarker* markers,size_t markerCount,
 const RuntimeDial* dials,size_t dialCount,int* error) {
 if(error)*error=-1;
 if(!error||!markers||!dials||markerCount!=3||dialCount<1||dialCount>32)return nullptr;
 try {
  std::unique_ptr<RuntimeProfile> p(new RuntimeProfile);
  polar::UserMarkerBox boxes[3];
  for(int i=0;i<3;++i){const auto& m=markers[i];
   if(m.w<8||m.h<8||m.w>128||m.h>128||!m.pixels||m.bytes!=size_t(m.w*m.h))return nullptr;
   boxes[i]={m.x,m.y,m.w,m.h};
  }
  if(!polar::markerBoxesValid(boxes,3)){*error=-2;return nullptr;}
  for(int i=0;i<3;++i){const auto& m=markers[i];
   p->pixels[i].assign(m.pixels,m.pixels+m.bytes);
   p->markers.markers[i]={p->pixels[i].data(),m.bytes,m.w,m.h,m.x,m.y,m.targetX,m.targetY};
  }
  if(!polar::validMarkerCalibration(p->markers)){*error=-2;return nullptr;}
  polar::MarkerMatch targets[3];
  for(int i=0;i<3;++i){const auto& m=p->markers.markers[i];targets[i]={m.targetX,m.targetY,m.targetX,m.targetY,1};}
  double identity[6];
  if(polar::confirmedRegistration(targets[0],targets[1],targets[2],3,identity)!=polar::AlignmentStatus::Ok){*error=-2;return nullptr;}
  for(size_t i=0;i<dialCount;++i){const auto& d=dials[i];
   if(d.anchorX<0||d.anchorX>=640||d.anchorY<0||d.anchorY>=480){*error=-3;return nullptr;}
   polar::DialGeometry candidate{};candidate.x=d.x;candidate.y=d.y;candidate.w=d.w;candidate.h=d.h;
   std::copy(d.inverse,d.inverse+9,candidate.inverse);std::copy(d.pivot,d.pivot+2,candidate.pivot);
   polar::ValidatedDialGeometry validated(candidate,d.anchorX,d.anchorY);
   if(!validated.get()){*error=-100-static_cast<int>(validated.status());return nullptr;}
   p->dials.push_back(validated);
  }
  *error=0;return p.release();
 }catch(...){*error=-4;return nullptr;}
}
API void aiedge_profile_destroy(void* handle){delete static_cast<RuntimeProfile*>(handle);}
API int aiedge_prepare_profile(void* handle,const uint8_t* rgb,size_t bytes,int sparse,
 int8_t* output,size_t capacity,int* states,double* visibility,size_t count){
 const auto* p=static_cast<const RuntimeProfile*>(handle);
 if(!p||!rgb||bytes!=640*480*3||count!=p->dials.size()||capacity!=count*384*40||!output||!states||!visibility||(sparse!=0&&sparse!=1))return -1;
 std::memset(output,0,capacity);for(size_t i=0;i<count;++i){states[i]=0;visibility[i]=-1;}
 try{
  std::unique_ptr<polar::PipelineScratch> scratch(new polar::PipelineScratch);double inverse[6];
  if(polar::alignFrame(rgb,640,480,*scratch,inverse,p->markers)!=polar::AlignmentStatus::Ok)return -2;
  for(size_t i=0;i<count;++i){
   const bool accepted=polar::prepareDial(rgb,inverse,p->dials[i],*scratch,nullptr,nullptr,sparse!=0);
   states[i]=static_cast<int>(scratch->preparationStatus);visibility[i]=scratch->visibilityScore;
   if(accepted)std::memcpy(output+i*384*40,scratch->features,384*40);
  }
  return 0;
 }catch(...){return -3;}
}

// Additive ABI 2 entry point. Values and error bounds use the printed 0..10
// dial scale; physical scales are source units per full revolution.
API int aiedge_reading(const double* revolutions,const double* positions,
 const double* errors,size_t count,double* output) {
 if(!revolutions||!positions||!errors||!output||count<1||count>16)return 0;
 meter::RevolutionDial dials[16];
 for(size_t i=0;i<count;++i)dials[i]={revolutions[i],positions[i],errors[i]};
 double candidate=0;
 const auto status=meter::reconstructRevolutions(dials,count,candidate);
 if(status==meter::RevolutionResult::Ready)*output=candidate;
 return static_cast<int>(status);
}
