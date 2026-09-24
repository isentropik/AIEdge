#include "MeterDisplayRuntime.h"
#include "cJSON.h"
#include <cassert>
#include <iostream>
using namespace meter;
int main(){
 RegisterProfile p;p.kind=MeterKind::Gas;p.sourceUnit=RegisterUnit::CubicFoot;p.displayUnit=RegisterUnit::CubicMetre;p.unitsPerRegisterCount=1;p.hasSecondary=true;p.secondaryUnitsPerRevolution=5;p.confirmed=true;
 assert(applyDisplayProfile(p)&&activeDisplayUnit()==RegisterUnit::CubicMetre);
 SessionResult s;s.state=SessionState::Interval;s.interval.status=Status::Estimated;s.interval.minimumFt3=4;s.interval.maximumFt3=6;s.interval.estimatedFt3=5;s.interval.elapsedSeconds=10;
 auto parsed=cJSON_Parse(statusWithDisplayJson(s,activeDisplayUnit()).c_str());assert(parsed);
 auto d=cJSON_GetObjectItem(parsed,"display"),i=cJSON_GetObjectItem(d,"interval");
 assert(cJSON_GetObjectItem(parsed,"estimated_ft3")->valuedouble==5);
 assert(std::abs(cJSON_GetObjectItem(i,"estimate")->valuedouble-5*.028316846592)<1e-10);
 assert(std::abs(cJSON_GetObjectItem(i,"average_per_second")->valuedouble-.5*.028316846592)<1e-10);cJSON_Delete(parsed);
 for(auto state:{SessionState::Empty,SessionState::Pending,SessionState::Rejected,SessionState::Restarted}){s.state=state;auto j=cJSON_Parse(displayJson(s,RegisterUnit::CubicMetre).c_str());auto x=cJSON_GetObjectItem(j,"interval");assert(cJSON_IsNull(cJSON_GetObjectItem(x,"estimate")));assert(cJSON_IsNull(cJSON_GetObjectItem(x,"minimum")));cJSON_Delete(j);}
 s.state=SessionState::Interval;s.interval.status=Status::Ambiguous;
 auto j=cJSON_Parse(displayJson(s,RegisterUnit::CubicMetre).c_str());i=cJSON_GetObjectItem(j,"interval");assert(cJSON_IsNumber(cJSON_GetObjectItem(i,"minimum")));assert(cJSON_IsNull(cJSON_GetObjectItem(i,"estimate")));cJSON_Delete(j);
 s.cumulative.available=true;s.cumulative.current=false;s.cumulative.minimumFt3=4;s.cumulative.maximumFt3=6;s.cumulative.estimatedFt3=5;s.cumulative.status=Status::Estimated;
 j=cJSON_Parse(displayJson(s,RegisterUnit::CubicMetre).c_str());auto c=cJSON_GetObjectItem(j,"cumulative_since_anchor");assert(cJSON_IsFalse(cJSON_GetObjectItem(c,"current")));assert(cJSON_IsNull(cJSON_GetObjectItem(c,"estimate")));assert(cJSON_IsNumber(cJSON_GetObjectItem(c,"minimum")));cJSON_Delete(j);
 p.kind=MeterKind::Water;assert(!applyDisplayProfile(p));assert(activeDisplayUnit()==RegisterUnit::Unknown);assert(displayJson(s,activeDisplayUnit())=="null");
 assert(displayNumber(-1,RegisterUnit::CubicFoot)=="null");assert(displayNumber(1,RegisterUnit::KWh)=="null");assert(!displayBounds(6,4));assert(!displayEstimate(Status::Estimated,7,4,6));
 std::cout<<"Converted status preserves canonical totals, bounds, ambiguity, stale state and calibration compatibility\n";
}
