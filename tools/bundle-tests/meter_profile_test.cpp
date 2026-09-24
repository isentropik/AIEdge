#include "MeterProfile.h"
#include <cassert>
#include <limits>
#include <cstdio>
int main(){using namespace meter;double result=99;
 assert(convertQuantity(1,RegisterUnit::CubicFoot,RegisterUnit::Litre,result));assert(std::abs(result-28.316846592)<1e-10);
 assert(convertQuantity(1,RegisterUnit::USGallon,RegisterUnit::Litre,result));assert(std::abs(result-3.785411784)<1e-10);
 assert(convertQuantity(1,RegisterUnit::ImperialGallon,RegisterUnit::Litre,result));assert(std::abs(result-4.54609)<1e-10);
 assert(convertQuantity(2500,RegisterUnit::Wh,RegisterUnit::KWh,result));assert(result==2.5);
 for(auto u:{RegisterUnit::CubicFoot,RegisterUnit::CubicMetre,RegisterUnit::Litre,RegisterUnit::USGallon,RegisterUnit::ImperialGallon}){
  double canonical,back;assert(convertQuantity(123.456,u,RegisterUnit::CubicMetre,canonical));assert(convertQuantity(canonical,RegisterUnit::CubicMetre,u,back));assert(std::abs(back-123.456)<1e-10);
 }
 result=99;assert(!convertQuantity(1,RegisterUnit::CubicFoot,RegisterUnit::KWh,result));assert(result==99);
 assert(!convertQuantity(1,RegisterUnit::Unknown,RegisterUnit::Unknown,result));assert(result==99);
 assert(!convertQuantity(std::numeric_limits<double>::infinity(),RegisterUnit::Wh,RegisterUnit::KWh,result));assert(result==99);
 RegisterProfile p;p.kind=MeterKind::Gas;p.sourceUnit=RegisterUnit::CubicFoot;p.displayUnit=RegisterUnit::CubicMetre;p.unitsPerRegisterCount=100;p.hasSecondary=true;p.secondaryUnitsPerRevolution=5;
 assert(!validProfile(p));p.confirmed=true;assert(validProfile(p));assert(registerQuantity(2,p,result));assert(std::abs(result-200*.028316846592)<1e-10);
 auto q=p;q.displayUnit=RegisterUnit::CubicFoot;assert(samePhysicalScale(p,q));q.unitsPerRegisterCount=1000;assert(!samePhysicalScale(p,q));
 q=p;q.sourceUnit=RegisterUnit::KWh;assert(!validProfile(q));q=p;q.hasSecondary=false;assert(!validProfile(q));q.secondaryUnitsPerRevolution=0;assert(validProfile(q));
 result=99;assert(!registerQuantity(-1,p,result));assert(result==99);
 p.unitsPerRegisterCount=std::numeric_limits<double>::max();assert(!registerQuantity(2,p,result));assert(result==99);
 puts("Physical unit conversions, multiplier, confirmation and migration checks passed");
}
