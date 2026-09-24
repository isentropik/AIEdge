#include "PolarPipeline.h"
#include <cassert>
#include <cstring>
#include <memory>
#include <vector>
#include <limits>
int main() {
    std::unique_ptr<polar::PipelineScratch> s(new polar::PipelineScratch);
    std::vector<uint8_t> rgb(640*480*3,0);
    double inverse[6]={1,0,0,0,1,0};
    for(bool sparse : {false,true}) {
        // A rejected frame must not report a previous frame's successful score.
        s->visibilityScore=100; s->preparationStatus=polar::PreparationStatus::Ok;
        assert(!polar::prepareDial(rgb.data(),inverse,-1,*s,nullptr,nullptr,sparse));
        assert(s->preparationStatus==polar::PreparationStatus::InvalidDial && s->visibilityScore==-1);
        assert(!polar::prepareDial(nullptr,inverse,0,*s,nullptr,nullptr,sparse));
        assert(s->preparationStatus==polar::PreparationStatus::Warp);
        inverse[0]=std::numeric_limits<double>::quiet_NaN();
        assert(!polar::prepareDial(rgb.data(),inverse,0,*s,nullptr,nullptr,sparse));
        assert(s->preparationStatus==polar::PreparationStatus::Warp);
        inverse[0]=1;
        for(uint8_t level : {uint8_t(0),uint8_t(128),uint8_t(255)}) {
            std::fill(rgb.begin(),rgb.end(),level);
            assert(!polar::prepareDial(rgb.data(),inverse,0,*s,nullptr,nullptr,sparse));
            assert(s->preparationStatus==polar::PreparationStatus::LowContrast);
            assert(s->visibilityScore==-1);
        }
    }
    assert(std::strcmp(polar::preparationStatusName(polar::PreparationStatus::LowVisibility),"needle_visibility_low")==0);
}
