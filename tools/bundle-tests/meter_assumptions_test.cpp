#include "MeterAssumptions.h"
#include <cassert>
#include <limits>
int main(){
 using namespace meter;
 Assumptions a;Bounds b;std::string name;
 assert(parseAssumptions(R"({"version":1,"maximum_flow_ft3_hour":null})",a));
 assert(assumptionBounds(a,b)&&!b.hasMaximumRate&&b.maximumRateFt3S==0);
 assert(assumptionNamespace(a,name)&&name=="polar-meter-reference");
 assert(parseAssumptions(R"({"version":1,"maximum_flow_ft3_hour":360})",a));
 assert(assumptionBounds(a,b)&&b.maximumRateFt3S==.1&&b.mainDial==.1&&b.secondaryDial==.1);
 assert(assumptionNamespace(a,name));const auto first=name;
 assert(first=="polar-meter-reference-rate-v1-3fb999999999999a");
 a.maximumFlowFt3Hour=720;assert(assumptionNamespace(a,name)&&name!=first);
 for(const char* bad:{"{}","[]",R"({"version":2,"maximum_flow_ft3_hour":1})",
 R"({"version":1,"maximum_flow_ft3_hour":0})",R"({"version":1,"maximum_flow_ft3_hour":-1})",
 R"({"version":1,"maximum_flow_ft3_hour":"360"})",R"({"version":1,"maximum_flow_ft3_hour":true})",
 R"({"version":1,"maximum_flow_ft3_hour":1e999})",R"({"version":1,"maximum_flow_ft3_hour":1e-999})",
 R"({"version":1,"maximum_flow_ft3_hour":null,"extra":1})",
 R"({"version":1,"version":1,"maximum_flow_ft3_hour":null})",
 R"({"version":1,"maximum_flow_ft3_hour":null,"maximum_flow_ft3_hour":1})",
 R"({"version":1,"maximum_flow_ft3_hour":null} trailing)"}) {
  assert(!parseAssumptions(bad,a));assert(a.hasMaximumFlow&&a.maximumFlowFt3Hour==720);
 }
 a.maximumFlowFt3Hour=std::numeric_limits<double>::denorm_min();
 assert(!assumptionBounds(a,b)&&b.maximumRateFt3S==.1);
 assert(!assumptionNamespace(a,name));
 a.maximumFlowFt3Hour=std::numeric_limits<double>::infinity();assert(!validAssumptions(a));
 a.hasMaximumFlow=false;assert(!validAssumptions(a));
}
