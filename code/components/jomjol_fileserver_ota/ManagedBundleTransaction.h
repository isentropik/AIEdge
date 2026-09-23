#pragma once
#include "InstallBundleIndex.h"
#include <functional>
namespace MeterBundle {
// Flash implementation invokes the callback only after SDK validation and input
// close; passes the target partition's actual app digest; selects boot only if
// callback succeeds. Caller holds exclusive update/storage ownership throughout.
template<class Hash,class Flash> bool install(const std::string& base,
 const std::string& id,const std::string& running,const std::string& model,Flash& flash) {
 if(!hashValid(id)||!hashValid(running)||!hashValid(model))return false;
 Manifest candidate;
 const std::string object=base+"/objects/"+id;
 if(!verify<Hash>(object,id,candidate).verified ||
    candidate.bootPolicy!="required_bundle" || candidate.appHash==running || candidate.modelHash!=model)return false;
 return flash.writeAndSelect(object+"/firmware/firmware.bin",
  [&](const std::string& flashedHash){
   if(flashedHash!=candidate.appHash)return false;
   const auto result=prepareIndex<Hash>(base,id,running,model);
   return result==IndexResult::Installed||result==IndexResult::Existing;
  });
}
}
