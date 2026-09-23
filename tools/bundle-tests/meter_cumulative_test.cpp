
#include "MeterStatus.h"
#include "MeterCheckpoint.h"
#include <cassert>
#include <iostream>
using namespace meter;
Frame frame(double total,int64_t time,uint64_t boot=1){
 Frame f{};double divisor=1000000;
 for(int i=0;i<5;++i,divisor/=10)f.main[i]=std::fmod(total/divisor,10);
 f.secondary=std::fmod(2*(total-1000)+1+10000,10);
 f.captureUs=time;f.captureTimeValid=true;f.clockId=boot;return f;
}
int main(){
 // Unique consecutive phase intervals must retain observed whole turns even
 // once the first/last endpoints alone cannot disambiguate them.
 Bounds tracked;tracked.hasMaximumRate=true;tracked.maximumRateFt3S=.1;
 Session turns(tracked);turns.observe(frame(1000,1000000));
 for(int i=1;i<=40;++i){
  turns.observe(frame(1000+i*2,1000000LL+i*30000000LL));
  assert(turns.current().state==SessionState::Interval);
  assert(std::abs(turns.current().cumulative.estimatedFt3-i*2)<1e-6);
 }
 // Checkpoints retain a conservative lower bound, not the volatile tracking
 // path. Reconstructed history may widen but must contain the tracked result.
 Checkpoint cp;cp.modelHash=std::string(64,'a');cp.calibrationHash=std::string(64,'b');cp.bounds=tracked;
 cp.hasSegment=turns.cumulativeAnchor(cp.anchor);turns.referenceFrame(cp.reference);
 cp.minimumFt3=turns.current().cumulative.minimumFt3;
 assert(checkpointValid(cp));CumulativeResult recovered;assert(checkpointSegment(cp,recovered));
 assert(recovered.minimumFt3==cp.minimumFt3&&recovered.maximumFt3>=80);
 // A long missing-image interval can hide whole turns. Do not extrapolate the
 // previous uniquely tracked rate through the gap.
 turns.observe(frame(1082,3001000000LL));
 assert(std::isnan(turns.current().cumulative.estimatedFt3));
 Session phaseJitter(tracked);auto initial=frame(1000,1);initial.secondary=9.98;phaseJitter.observe(initial);
 for(int i=1;i<=2000;++i){
  auto f=frame(1000,1+i*30000000LL);f.secondary=(i%2)? .02:9.98;
  phaseJitter.observe(f);const auto c=phaseJitter.current().cumulative;
  assert(c.current&&c.minimumFt3==0&&std::isnan(c.estimatedFt3));
 }
 Bounds b;b.mainDial=0;b.secondaryDial=.1;
 Session jitter(b);jitter.observe(frame(1000,1));
 for(int i=1;i<=2000;i++){
  auto f=frame(1000,i*1000000LL);f.secondary+=(i%2 ? .08 : -.08);
  jitter.observe(f);const auto& c=jitter.current().cumulative;
  assert(c.current&&c.minimumFt3==0&&c.maximumFt3<1e-6);
  assert(std::isnan(c.estimatedFt3));
 }
 // Each tiny movement is below the secondary noise bound; over the fixed
 // anchor it must still produce consumption, rather than being discarded.
 Session slow(b);slow.observe(frame(1000,1));
 for(int i=1;i<=500;i++){
  slow.observe(frame(1000+i*.02,i*1000000LL));
  auto c=slow.current().cumulative;
  assert(c.current&&c.minimumFt3<=i*.02+1e-6&&c.maximumFt3>=i*.02-1e-6);
 }
 assert(std::abs(slow.current().cumulative.estimatedFt3-10)<1e-6);
 assert(slow.current().cumulative.anchorUs==1);
 // Missing frames include the entire gap; twenty secondary turns are 100 ft3.
 slow.reject(Reason::SecondaryUnknown);
 assert(!slow.current().cumulative.current);
 slow.observe(frame(1100,600000000));
 assert(std::abs(slow.current().cumulative.estimatedFt3-100)<1e-6);
 std::cout<<statusJson(slow.current())<<"\n";
 slow.begin();std::cout<<statusJson(slow.current())<<"\n";
 slow.observe(frame(1101,1,2));
 assert(slow.current().state==SessionState::Restarted);
 assert(slow.current().cumulative.minimumFt3==0&&slow.current().cumulative.maximumFt3==0);
 assert(slow.current().cumulative.anchorUs==1);
 // Default uncertainty must not be replaced by a guessed turn count.
 Session ambiguous;ambiguous.observe(frame(1000,1));ambiguous.observe(frame(1000,30000001));
 assert(ambiguous.current().cumulative.status==Status::Ambiguous);
 assert(std::isnan(ambiguous.current().cumulative.estimatedFt3));
 // A slowly drifting series can pass each adjacent check while contradicting
 // the anchor. Reject the eventual contradiction without moving the reference.
 Bounds loose;loose.mainDial=.01;loose.secondaryDial=.1;
 Session drift(loose);drift.observe(frame(1100,1));
 for(int i=1;i<=3;i++){
  auto f=frame(1100-i*.5,i*1000000);f.secondary=1;
  drift.observe(f);assert(drift.current().state==SessionState::Interval);
 }
 const auto retained=drift.current().referenceCaptureUs;
 auto contradiction=frame(1097.9,4000000);contradiction.secondary=1;
 drift.observe(contradiction);
 assert(drift.current().state==SessionState::Rejected);
 assert(drift.current().interval.reason==Reason::CumulativeContradiction);
 assert(drift.current().referenceCaptureUs==retained);
}
