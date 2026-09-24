#pragma once
#include "MeterDisplayRuntime.h"
#include "../jomjol_tfliteclass/MeterProfileStore.h"
namespace meter {
// Called before HTTP/recognition tasks start, or under ProcessingAccess during
// flow reload. Camera availability must not control a saved display preference.
inline const char* restoreDisplayProfile(ConfigJournal::Storage& storage,
                                        const std::string& path,bool storageReady=true){
 applyDisplayProfile(RegisterProfile{});
 if(!storageReady)return "Meter settings storage unavailable";
 const auto recovered=ProfileStore::recoverSettings(storage,path);
 if(recovered!=ConfigJournal::Result::Ok&&recovered!=ConfigJournal::Result::CleanupPending)
  return "Meter settings recovery required";
 std::string bytes;RegisterProfile profile;
 const auto read=storage.read(path,bytes);
 if(read==ConfigJournal::Read::Error||(read==ConfigJournal::Read::Ok&&!parseProfile(bytes,profile)))
  return "Meter settings unavailable";
 applyDisplayProfile(profile);
 return nullptr;
}
}
