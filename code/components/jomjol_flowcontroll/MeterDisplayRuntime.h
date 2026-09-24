#pragma once
#include "MeterDisplay.h"
#include <atomic>
namespace meter {
// One scalar preference: atomic publication prevents mixed units between readers.
inline std::atomic<int>& displayPreference(){static std::atomic<int> value{int(RegisterUnit::Unknown)};return value;}
inline RegisterUnit activeDisplayUnit(){return RegisterUnit(displayPreference().load());}
inline bool applyDisplayProfile(const RegisterProfile& profile){
 const bool compatible=matchesFrozenGasScale(profile);
 displayPreference().store(int(compatible?profile.displayUnit:RegisterUnit::Unknown));return compatible;
}
}
