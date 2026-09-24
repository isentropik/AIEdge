#pragma once
#include <cmath>
namespace meter {
// Physical units are separate from normalized needle positions and MQTT labels.
enum class MeterKind { Unknown, Gas, Water, Electricity };
enum class RegisterUnit { Unknown, CubicFoot, CubicMetre, Litre, USGallon, ImperialGallon, Wh, KWh };
enum class Dimension { Unknown, Volume, Energy };
inline Dimension dimension(RegisterUnit u) {
 switch(u){case RegisterUnit::CubicFoot:case RegisterUnit::CubicMetre:case RegisterUnit::Litre:
 case RegisterUnit::USGallon:case RegisterUnit::ImperialGallon:return Dimension::Volume;
 case RegisterUnit::Wh:case RegisterUnit::KWh:return Dimension::Energy;default:return Dimension::Unknown;}
}
// Canonical quantities are cubic metres and kilowatt-hours; never interconvert them.
inline double canonicalFactor(RegisterUnit u) {
 switch(u){case RegisterUnit::CubicFoot:return .028316846592;case RegisterUnit::CubicMetre:return 1;
 case RegisterUnit::Litre:return .001;case RegisterUnit::USGallon:return .003785411784;
 case RegisterUnit::ImperialGallon:return .00454609;case RegisterUnit::Wh:return .001;
 case RegisterUnit::KWh:return 1;default:return 0;}
}
inline bool supports(MeterKind kind,RegisterUnit unit) {
 switch(kind){case MeterKind::Gas:return unit==RegisterUnit::CubicFoot || unit==RegisterUnit::CubicMetre;
 case MeterKind::Water:return dimension(unit)==Dimension::Volume;
 case MeterKind::Electricity:return dimension(unit)==Dimension::Energy;default:return false;}
}
inline bool convertQuantity(double value,RegisterUnit from,RegisterUnit to,double& result) {
 if(!std::isfinite(value)||dimension(from)==Dimension::Unknown||dimension(from)!=dimension(to))return false;
 const double converted=value*(canonicalFactor(from)/canonicalFactor(to));
 if(!std::isfinite(converted))return false;
 result=converted;return true;
}
struct RegisterProfile {
 MeterKind kind=MeterKind::Unknown;
 RegisterUnit sourceUnit=RegisterUnit::Unknown,displayUnit=RegisterUnit::Unknown;
 double unitsPerRegisterCount=0; // Includes the multiplier printed on the meter.
 bool hasSecondary=false;
 double secondaryUnitsPerRevolution=0; // In sourceUnit, never in normalized 0-10 positions.
 bool confirmed=false;
};
inline bool validProfile(const RegisterProfile& p) {
 return p.confirmed && supports(p.kind,p.sourceUnit) && supports(p.kind,p.displayUnit) &&
  std::isfinite(p.unitsPerRegisterCount) && p.unitsPerRegisterCount>0 &&
  std::isfinite(p.secondaryUnitsPerRevolution) &&
  (p.hasSecondary?p.secondaryUnitsPerRevolution>0:p.secondaryUnitsPerRevolution==0);
}
inline bool registerQuantity(double count,const RegisterProfile& p,double& result) {
 if(!validProfile(p)||!std::isfinite(count)||count<0)return false;
 return convertQuantity(count*p.unitsPerRegisterCount,p.sourceUnit,p.displayUnit,result);
}
// Display-unit changes do not change the physical interpretation of stored counts.
// A false result requires an explicit history migration/new measurement epoch.
inline bool samePhysicalScale(const RegisterProfile& a,const RegisterProfile& b) {
 if(!validProfile(a)||!validProfile(b))return false;
 return a.kind==b.kind && a.sourceUnit==b.sourceUnit &&
  a.unitsPerRegisterCount==b.unitsPerRegisterCount && a.hasSecondary==b.hasSecondary &&
  a.secondaryUnitsPerRevolution==b.secondaryUnitsPerRevolution;
}
}
