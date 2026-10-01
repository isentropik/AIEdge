#pragma once
#include "PolarAlignment.h"
#include "PolarImage.h"
#include "PolarWarp.h"
#include "PolarFeatures.h"
#include "PolarCalibration.h"
#include "PolarRuntimeGeometry.h"
#include "PolarAlignmentCheck.h"
#include "PolarVisibility.h"
#include "PolarProfile.h"
#include "PolarCoarseAlignment.h"

namespace polar {
enum class PreparationStatus { NotStarted, InvalidDial, Warp, Grayscale, LowContrast,
    VisibilityCalculation, LowVisibility, Blur, Coordinates, Features, Ok };
inline const char* preparationStatusName(PreparationStatus status) {
    switch(status) {
    case PreparationStatus::NotStarted: return "not_started";
    case PreparationStatus::InvalidDial: return "invalid_dial";
    case PreparationStatus::Warp: return "crop_transform_failed";
    case PreparationStatus::Grayscale: return "grayscale_failed";
    case PreparationStatus::LowContrast: return "low_contrast";
    case PreparationStatus::VisibilityCalculation: return "visibility_calculation_failed";
    case PreparationStatus::LowVisibility: return "needle_visibility_low";
    case PreparationStatus::Blur: return "filter_failed";
    case PreparationStatus::Coordinates: return "sampling_geometry_invalid";
    case PreparationStatus::Features: return "feature_extraction_failed";
    case PreparationStatus::Ok: return "ok";
    }
    return "unknown";
}
// Allocate once in PSRAM/on heap, not on the task stack. Six dials reuse buffers.
struct PipelineScratch {
    uint8_t fullGray[640*480];
    uint8_t crop[148*148*3],gray[148*148],temporary[148*148];
    double scores[1681],coordinates[14400],samples[7200],sorted[360];
    int8_t features[384*40];
    double visibilityScore;
    PreparationStatus preparationStatus;
};
inline AlignmentStatus alignGrayLocal(int width,int height,
                                  PipelineScratch& scratch,double* inverse,
                                  const MarkerCalibration& calibration=frozenMarkerCalibration()) {
    if(!inverse || width!=calibratedWidth || height!=calibratedHeight || !validMarkerCalibration(calibration))
        return AlignmentStatus::InvalidInput;
    MarkerMatch matches[3];
    for(int i=0;i<3;++i){
        const auto& m=calibration.markers[i];
        auto status=matchMarker(scratch.fullGray,width,height,m.pixels,m.width,m.height,
                                m.searchX,m.searchY,scratch.scores,1681,matches[i]);
        if(status!=AlignmentStatus::Ok)return status;
        matches[i].targetX=m.targetX;matches[i].targetY=m.targetY;
    }
    // Provisional three-pixel consistency limit; independent real captures still required.
    double forward[6];auto status=confirmedRegistration(matches[0],matches[1],matches[2],3.0,forward);
    if(status!=AlignmentStatus::Ok)return status;
    const double determinant=forward[0]*forward[4]-forward[1]*forward[3];
    inverse[0]=forward[4]/determinant;inverse[1]=-forward[1]/determinant;
    inverse[3]=-forward[3]/determinant;inverse[4]=forward[0]/determinant;
    inverse[2]=-(inverse[0]*forward[2]+inverse[1]*forward[5]);
    inverse[5]=-(inverse[3]*forward[2]+inverse[4]*forward[5]);
    return AlignmentStatus::Ok;
}
inline AlignmentStatus alignFrameLocal(const uint8_t* rgb,int width,int height,
                                  PipelineScratch& scratch,double* inverse,
                                  const MarkerCalibration& calibration=frozenMarkerCalibration()) {
    if(!rgb||width!=calibratedWidth||height!=calibratedHeight)return AlignmentStatus::InvalidInput;
    grayscale(rgb,width*height,scratch.fullGray);
    return alignGrayLocal(width,height,scratch,inverse,calibration);
}
inline AlignmentStatus alignGrayFrame(PipelineScratch& scratch,double* inverse,
                                  const MarkerCalibration& calibration=frozenMarkerCalibration()) {
    const auto status=alignGrayLocal(640,480,scratch,inverse,calibration);
    if(status!=AlignmentStatus::Boundary&&status!=AlignmentStatus::WeakMatch)return status;
    return alignFrameCoarse(scratch.fullGray,reinterpret_cast<uint8_t*>(scratch.coordinates),
                           sizeof(scratch.coordinates),scratch.scores,inverse,calibration);
}
// Preserve the established fast path exactly. Ambiguous or geometrically
// contradictory matches must not be retried with a more permissive search.
inline AlignmentStatus alignFrame(const uint8_t* rgb,int width,int height,
                                  PipelineScratch& scratch,double* inverse,
                                  const MarkerCalibration& calibration=frozenMarkerCalibration()) {
    const auto status=alignFrameLocal(rgb,width,height,scratch,inverse,calibration);
    if(status!=AlignmentStatus::Boundary && status!=AlignmentStatus::WeakMatch)return status;
    // Coordinates are not live until prepareDial. Character access safely reuses
    // their storage for a half-resolution grayscale image without growing PSRAM.
    static_assert(sizeof(scratch.coordinates)>=320*240,"Insufficient alignment scratch");
    return alignFrameCoarse(scratch.fullGray,reinterpret_cast<uint8_t*>(scratch.coordinates),
                            sizeof(scratch.coordinates),scratch.scores,inverse,calibration);
}
inline bool prepareDialGeometry(const uint8_t* rgb,const double* inverse,const DialGeometry* geometry,PipelineScratch& scratch,
                        DialProfile* profile=nullptr,int64_t (*clock)()=nullptr, bool sparse=false,int phaseX=0,int phaseY=0) {
    scratch.preparationStatus=PreparationStatus::InvalidDial;
    scratch.visibilityScore=-1;
    if(profile)*profile=DialProfile{};
    if(!geometry)return false;
    DialProfileTimer timing(profile,clock);
    const auto& d=*geometry;
    scratch.preparationStatus=PreparationStatus::Warp;
    if(!warpCrop(rgb,640,480,inverse,d.x,d.y,d.w,d.h,scratch.crop,sparse,phaseX,phaseY))return false;
    timing.next();
    scratch.preparationStatus=PreparationStatus::Grayscale;
    if(!grayscale(scratch.crop,d.w*d.h,scratch.gray))return false;
    scratch.preparationStatus=PreparationStatus::LowContrast;
    if(!contrastValid(scratch.gray,d.w*d.h))return false;
    timing.next();
    scratch.preparationStatus=PreparationStatus::VisibilityCalculation;
    if(!visibility(scratch.gray,d,scratch.samples,scratch.sorted,scratch.visibilityScore))return false;
    scratch.preparationStatus=PreparationStatus::LowVisibility;
    if(scratch.visibilityScore<visibilityThreshold)return false;
    timing.next();
    scratch.preparationStatus=PreparationStatus::Blur;
    if(!blur04(scratch.gray,scratch.temporary,d.w,d.h))return false;
    timing.next();
    scratch.preparationStatus=PreparationStatus::Coordinates;
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
    scratch.preparationStatus=PreparationStatus::Features;
    if(!features(scratch.gray,d.w,d.h,scratch.coordinates,scratch.samples,scratch.sorted,scratch.features,384*40))return false;
    scratch.preparationStatus=PreparationStatus::Ok;
    return true;
}
// Compiled calibration retains its existing path. Runtime candidates validate
// once, before activation; no 11,520-point geometry scan is added per frame.
inline bool prepareDial(const uint8_t* rgb,const double* inverse,int index,PipelineScratch& scratch,
                        DialProfile* profile=nullptr,int64_t (*clock)()=nullptr,bool sparse=false) {
    return prepareDialGeometry(rgb,inverse,index>=0&&index<6?&dials[index]:nullptr,scratch,profile,clock,sparse);
}
inline bool prepareDial(const uint8_t* rgb,const double* inverse,const ValidatedDialGeometry& geometry,
                        PipelineScratch& scratch,DialProfile* profile=nullptr,
                        int64_t (*clock)()=nullptr,bool sparse=false) {
    return prepareDialGeometry(rgb,inverse,geometry.get(),scratch,profile,clock,sparse,geometry.samplingPhaseX(),geometry.samplingPhaseY());
}

}
