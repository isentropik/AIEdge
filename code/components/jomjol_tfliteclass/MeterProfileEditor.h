#pragma once
#include "MeterProfileStore.h"
#include "../jomjol_controlcamera/FileConfigStorage.h"
namespace meter {
struct ProfileSnapshot {bool existed=false;std::string bytes,revision;RegisterProfile profile;};
// Inspection is read-only; unresolved recovery must not look like an empty setup.
template<class Hash> bool inspectProfile(ConfigJournal::Storage& disk,const std::string& path,ProfileSnapshot& output){
 std::string journal,body;
 if(disk.read(path+".journal",journal)!=ConfigJournal::Read::Missing)return false;
 ProfileSnapshot next;auto status=disk.read(path,body);
 if(status==ConfigJournal::Read::Error)return false;
 if(status==ConfigJournal::Read::Ok){if(!parseProfile(body,next.profile))return false;next.existed=true;next.bytes=body;}
 Hash hash;const std::string tagged=(next.existed?"profile-v1:":"missing-profile-v1:")+next.bytes;
 if(!hash.update(reinterpret_cast<const unsigned char*>(tagged.data()),tagged.size()))return false;
 next.revision=hash.finish();if(next.revision.size()!=64)return false;
 output=next;return true;
}
}
