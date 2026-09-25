// Physical oracle: derive dial positions from known volume, then add bounded
// sensor error. Do not derive expected volume using the implementation under test.
#include "MeterSession.h"
#include <cmath>
#include <cstdint>
#include <iostream>
#include <random>
using namespace meter;
static std::mt19937 randomSource(0xa1ed9e);
static double unit(){return double(randomSource())/4294967295.0;}
static double wrap(double x){x=std::fmod(x,10.0);return x<0?x+10:x;}
static Frame sample(double volume,int64_t time,double phase,double noise){
 Frame f{};const double step[]={1000000,100000,10000,1000,100};
 for(int i=0;i<5;++i)f.main[i]=wrap(volume/step[i]+noise*(2*unit()-1));
 f.secondary=wrap(volume*2+phase+noise*(2*unit()-1));
 f.captureUs=time;f.captureTimeValid=true;f.clockId=1;return f;
}
static bool contains(double lo,double hi,double truth){return lo<=truth+1e-6&&hi>=truth-1e-6;}
int main(){
 unsigned intervals=0,frames=0;
 for(unsigned i=0;i<20000;++i){
  const double start=unit()*9900000,delta=unit()*3000,phase=unit()*10;
  Bounds b;b.mainDial=.1;b.secondaryDial=.1;
  b.hasMaximumRate=(i%2)==0;b.maximumRateFt3S=delta/30+.01;
  auto a=sample(start,1000000,phase,.1),z=sample(start+delta,31000000,phase,.1);
  const auto r=resolve(a,z,b);
  if(r.status==Status::Invalid||r.status==Status::Review||!contains(r.minimumFt3,r.maximumFt3,delta)){
   std::cerr<<"interval truth excluded at case "<<i<<" reason "<<int(r.reason)<<"\n";return 1;
  }
  ++intervals;
 }
 for(unsigned stream=0;stream<100;++stream){
  Bounds b;b.hasMaximumRate=true;b.maximumRateFt3S=.1;
  Session session(b);const double start=unit()*9900000,phase=unit()*10;
  double volume=start;int64_t time=1000000;
  session.observe(sample(volume,time,phase,.1));
  for(unsigned i=1;i<=200;++i){
   // Stationary jitter, small increments, phase wraps, and a missing-frame gap.
   const int seconds=i%37==0?300:30;
   volume+=stream%5==0?0:unit()*.09*seconds;time+=int64_t(seconds)*1000000;
   if(i%37==0)session.reject(Reason::SecondaryUnknown);
   session.observe(sample(volume,time,phase,.1));
   const auto& c=session.current().cumulative;
   if(session.current().state!=SessionState::Interval||!c.current||!contains(c.minimumFt3,c.maximumFt3,volume-start)){
    std::cerr<<"stream truth excluded at "<<stream<<":"<<i<<" reason "<<int(session.current().interval.reason)<<"\n";return 1;
   }
   ++frames;
  }
 }
 // Exact carries across every main-dial boundary below full-register rollover.
 for(double boundary: {1000.,10000.,100000.,1000000.}){
  Bounds b;b.mainDial=0;b.secondaryDial=0;
  auto r=resolve(sample(boundary-2,1000000,0,0),sample(boundary+3,31000000,0,0),b);
  if(r.status!=Status::Estimated||std::abs(r.estimatedFt3-5)>1e-6)return 1;
 }
 // Endpoint phases cannot distinguish 0 from 20 ft3 at default uncertainty.
 auto unresolved=resolve(sample(1000,1000000,0,0),sample(1000,31000000,0,0),Bounds{});
 if(unresolved.status!=Status::Ambiguous||std::isfinite(unresolved.estimatedFt3))return 1;
 // Full-register rollover and a true backward total require review.
 Bounds exact;exact.mainDial=0;exact.secondaryDial=0;
 if(resolve(sample(9999999,1000000,0,0),sample(1,31000000,0,0),exact).reason!=Reason::RegisterRolloverOrReset)return 1;
 if(resolve(sample(1005,1000000,0,0),sample(1000,31000000,0,0),exact).reason!=Reason::BackwardMain)return 1;
 std::cout<<intervals<<" physical intervals and "<<frames<<" cumulative frames passed; carries and ambiguity checks passed.\n";
}
