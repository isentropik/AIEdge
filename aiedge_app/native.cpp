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
 struct CachedDial {
  bool valid=false;
  double visibility=-1;
  std::vector<int8_t> features;
 };
 std::vector<uint8_t> pixels[3];
 polar::MarkerCalibration markers{};
 std::vector<polar::ValidatedDialGeometry> dials;
 // Server-side only: retain one frame, not an expanding history of dial crops.
 std::vector<uint8_t> previous;
 std::vector<CachedDial> cache;
 double previousInverse[6]{};
 int previousSparse=-1;
 void clearReuse(){previous.clear();previousSparse=-1;for(auto& c:cache)c.valid=false;}
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
  p->cache.resize(dialCount);
  *error=0;return p.release();
 }catch(...){*error=-4;return nullptr;}
}
API void aiedge_profile_destroy(void* handle){delete static_cast<RuntimeProfile*>(handle);}
// With the SAME affine transform, every bicubic tap for a crop lies in this
// conservative source rectangle. Compare RGB bytes directly, without warping
// or making a crop. Three extra pixels cover the 4x4 taps and rounding at edges.
static bool unchangedSource(const uint8_t* rgb,const std::vector<uint8_t>& previous,
 const double* inverse,const polar::DialGeometry& d){
 if(previous.size()!=640*480*3)return false;
 double minX=640,maxX=-1,minY=480,maxY=-1;
 for(int row:{0,d.h-1})for(int col:{0,d.w-1}){
  const double x=d.x+col+.5,y=d.y+row+.5;
  const double sx=inverse[0]*x+inverse[1]*y+inverse[2];
  const double sy=inverse[3]*x+inverse[4]*y+inverse[5];
  if(!std::isfinite(sx)||!std::isfinite(sy))return false;
  minX=std::min(minX,sx);maxX=std::max(maxX,sx);
  minY=std::min(minY,sy);maxY=std::max(maxY,sy);
 }
 // An entirely off-frame crop must go through the normal rejection path.
 if(maxX<0||maxY<0||minX>=640||minY>=480)return false;
 const int left=int(std::max(0.0,std::min(639.0,std::floor(minX)-3)));
 const int right=int(std::max(0.0,std::min(639.0,std::ceil(maxX)+3)));
 const int top=int(std::max(0.0,std::min(479.0,std::floor(minY)-3)));
 const int bottom=int(std::max(0.0,std::min(479.0,std::ceil(maxY)+3)));
 for(int y=top;y<=bottom;++y){
  const size_t start=size_t(y*640+left)*3,length=size_t(right-left+1)*3;
  if(std::memcmp(rgb+start,previous.data()+start,length))return false;
 }
 return true;
}
static int prepareRuntime(void* handle,const uint8_t* rgb,size_t bytes,int sparse,
 int8_t* output,size_t capacity,int* states,double* visibility,size_t count,int* reused){
 auto* p=static_cast<RuntimeProfile*>(handle);
 if(!p||!rgb||bytes!=640*480*3||count!=p->dials.size()||capacity!=count*384*40||!output||!states||!visibility||(sparse!=0&&sparse!=1))return -1;
 std::memset(output,0,capacity);for(size_t i=0;i<count;++i){states[i]=0;visibility[i]=-1;if(reused)reused[i]=0;}
 try{
  std::unique_ptr<polar::PipelineScratch> scratch(new polar::PipelineScratch);double inverse[6];
  if(polar::alignFrame(rgb,640,480,*scratch,inverse,p->markers)!=polar::AlignmentStatus::Ok){p->clearReuse();return -2;}
  const bool sameTransform=reused&&p->previousSparse==sparse&&
   std::memcmp(inverse,p->previousInverse,sizeof(inverse))==0;
  for(size_t i=0;i<count;++i){
   auto& cached=p->cache[i];
   if(sameTransform&&cached.valid&&unchangedSource(rgb,p->previous,inverse,*p->dials[i].get())){
    states[i]=static_cast<int>(polar::PreparationStatus::Ok);visibility[i]=cached.visibility;
    std::memcpy(output+i*384*40,cached.features.data(),384*40);reused[i]=1;continue;
   }
   const bool accepted=polar::prepareDial(rgb,inverse,p->dials[i],*scratch,nullptr,nullptr,sparse!=0);
   states[i]=static_cast<int>(scratch->preparationStatus);visibility[i]=scratch->visibilityScore;
   if(accepted)std::memcpy(output+i*384*40,scratch->features,384*40);
   cached.valid=reused&&accepted;
   if(cached.valid){cached.visibility=visibility[i];cached.features.assign(scratch->features,scratch->features+384*40);}
  }
  if(reused){p->previous.assign(rgb,rgb+bytes);std::copy(inverse,inverse+6,p->previousInverse);p->previousSparse=sparse;}
  else p->clearReuse();
  return 0;
 }catch(...){p->clearReuse();return -3;}
}
API int aiedge_prepare_profile(void* handle,const uint8_t* rgb,size_t bytes,int sparse,
 int8_t* output,size_t capacity,int* states,double* visibility,size_t count){
 return prepareRuntime(handle,rgb,bytes,sparse,output,capacity,states,visibility,count,nullptr);
}
// Additive ABI 2 entry point. Calls on a profile must be serialized by its owner.
// Rejections are never reused; a failed alignment invalidates all cached crops.
API int aiedge_prepare_profile_reuse(void* handle,const uint8_t* rgb,size_t bytes,int sparse,
 int8_t* output,size_t capacity,int* states,double* visibility,size_t count,int* reused){
 if(!reused)return -1;
 return prepareRuntime(handle,rgb,bytes,sparse,output,capacity,states,visibility,count,reused);
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
