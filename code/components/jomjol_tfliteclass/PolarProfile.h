#pragma once
#include <cstdint>
namespace polar {
// Diagnostic-only timings, in execution order. Zero mask means not measured.
struct DialProfile { int64_t us[6]={}; unsigned attemptedMask=0; };
class DialProfileTimer {
 DialProfile* profile_; int64_t (*clock_)(); int stage_=0; int64_t start_=0;
 void begin(){if(profile_){profile_->attemptedMask|=1u<<stage_;start_=clock_();}}
 void end(){if(profile_)profile_->us[stage_]=clock_()-start_;}
public:
 DialProfileTimer(DialProfile* profile,int64_t (*clock)()):profile_(clock?profile:nullptr),clock_(clock){if(profile_)*profile_=DialProfile{};begin();}
 ~DialProfileTimer(){end();}
 void next(){end();++stage_;begin();}
 DialProfileTimer(const DialProfileTimer&)=delete;
 DialProfileTimer& operator=(const DialProfileTimer&)=delete;
};
}
