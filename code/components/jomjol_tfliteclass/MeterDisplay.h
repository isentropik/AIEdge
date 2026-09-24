#pragma once
#include "MeterProfile.h"
#include "MeterStatus.h"
namespace meter {
inline bool displayUnitSupported(RegisterUnit u){return u==RegisterUnit::CubicFoot||u==RegisterUnit::CubicMetre;}
inline std::string displayNumber(double ft3,RegisterUnit unit){
 double result;if(ft3<0||!displayUnitSupported(unit)||!convertQuantity(ft3,RegisterUnit::CubicFoot,unit,result))return "null";
 return jsonNumber(result);
}
inline bool displayBounds(double lo,double hi){return std::isfinite(lo)&&std::isfinite(hi)&&lo>=0&&hi>=lo;}
inline bool displayEstimate(Status status,double estimate,double lo,double hi){return status==Status::Estimated&&displayBounds(lo,hi)&&std::isfinite(estimate)&&estimate>=lo&&estimate<=hi;}
// An additional view of canonical ft3 quantities. Never relabel stored values or
// turn an ambiguous interval, stale segment or absent observation into a point estimate.
inline std::string displayJson(const SessionResult& s,RegisterUnit unit){
 if(!displayUnitSupported(unit))return "null";
 const auto& i=s.interval;const auto& c=s.cumulative;
 const bool interval=s.state==SessionState::Interval&&i.status!=Status::Invalid&&i.status!=Status::Review&&displayBounds(i.minimumFt3,i.maximumFt3);
 const bool estimated=interval&&displayEstimate(i.status,i.estimatedFt3,i.minimumFt3,i.maximumFt3);
 const bool cumulative=c.available&&displayBounds(c.minimumFt3,c.maximumFt3);
 const bool cumulativeEstimate=cumulative&&c.current&&displayEstimate(c.status,c.estimatedFt3,c.minimumFt3,c.maximumFt3);
 const char* name=unit==RegisterUnit::CubicFoot?"ft3":"m3";
 std::string out="{\"unit\":\""+std::string(name)+"\",\"canonical_unit\":\"ft3\",\"interval\":{\"minimum\":"+(interval?displayNumber(i.minimumFt3,unit):"null")+
 ",\"maximum\":"+(interval?displayNumber(i.maximumFt3,unit):"null")+",\"estimate\":"+(estimated?displayNumber(i.estimatedFt3,unit):"null")+
 ",\"average_per_second\":"+(estimated&&std::isfinite(i.elapsedSeconds)&&i.elapsedSeconds>0?displayNumber(i.estimatedFt3/i.elapsedSeconds,unit):"null")+"},\"cumulative_since_anchor\":{\"current\":"+(cumulative&&c.current?"true":"false")+
 ",\"through_us\":"+std::to_string(c.throughUs)+",\"minimum\":"+(cumulative?displayNumber(c.minimumFt3,unit):"null")+",\"maximum\":"+(cumulative?displayNumber(c.maximumFt3,unit):"null")+
 ",\"estimate\":"+(cumulativeEstimate?displayNumber(c.estimatedFt3,unit):"null")+"}}";
 return out;
}
// A display-only view of completed history; canonical stored ft3 remain unchanged.
inline std::string historyDisplayJson(bool valid,double lo,double hi,RegisterUnit unit){
 if(!displayUnitSupported(unit))return "null";
 const bool available=valid&&displayBounds(lo,hi);
 const char* name=unit==RegisterUnit::CubicFoot?"ft3":"m3";
 return "{\"unit\":\""+std::string(name)+"\",\"canonical_unit\":\"ft3\",\"minimum\":"+
  (available?displayNumber(lo,unit):"null")+",\"maximum\":"+(available?displayNumber(hi,unit):"null")+"}";
}
inline std::string statusWithDisplayJson(const SessionResult& s,RegisterUnit unit){auto out=statusJson(s);out.pop_back();return out+",\"display\":"+displayJson(s,unit)+"}";}
}
