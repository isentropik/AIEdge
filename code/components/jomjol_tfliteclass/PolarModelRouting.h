#pragma once
#include "CTfLiteClass.h"
#include "../jomjol_fileserver_ota/RuntimeBundle.h"
namespace polar {
// A selected immutable bundle is mandatory; no legacy file or role fallback.
inline bool loadRole(CTfLiteClass& network, ModelRole role) {
 const auto* spec=modelSpec(role);
 if(!spec)return false;
 const auto path=MeterBundle::bootSelection().resolve(spec->asset, "");
 return !path.empty() && network.LoadPolarModel(path,role) &&
        network.MakeAllocate() && network.HasPolarTensorContract();
}
inline bool validateBothRoles(CTfLiteClass& network) {
 return loadRole(network,ModelRole::Main) && loadRole(network,ModelRole::Secondary);
}
}
