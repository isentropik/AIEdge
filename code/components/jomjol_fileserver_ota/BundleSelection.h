#pragma once
#include "VerifyDeviceBundle.h"
#include <cerrno>
namespace MeterBundle {
enum class SelectionState { Legacy, Rejected, Selected };
// Build before HTTP/capture tasks start. Immutable after the first load attempt.
// No file promotion, boot selection or flash writes are performed here.
class Selection {
 SelectionState state_=SelectionState::Legacy;
 bool attempted_=false;
 std::string root_;
 Manifest manifest_;
public:
 SelectionState state() const {return state_;}
 const std::string& id() const{return manifest_.id;}
 template<class Hash> bool load(const std::string& root,const std::string& bundleId,
                               const std::string& runningAppHash,const std::string& frozenModelHash,
                               const std::map<std::string,File>& requiredAssets={}){
  if(attempted_)return false;
  attempted_=true;state_=SelectionState::Rejected;
  if(!hashValid(runningAppHash)||!hashValid(frozenModelHash))return false;
  Manifest candidate;
  const auto checked=verify<Hash>(root,bundleId,candidate);
  if(!checked.verified||candidate.appHash!=runningAppHash||candidate.modelHash!=frozenModelHash)return false;
  // Requirements belong to the running application, not the supplied manifest.
  // Verify all role identities before making any bundle asset visible.
  for(const auto& item:requiredAssets){
   const auto found=candidate.assets.find(item.first);
   if(!item.second.bytes||!hashValid(item.second.hash)||found==candidate.assets.end()||
      found->second.bytes!=item.second.bytes||found->second.hash!=item.second.hash)return false;
  }
  root_=root;manifest_=candidate;state_=SelectionState::Selected;return true;
 }
 // Only immutable application assets are redirected. Config, images and logs
 // remain in their original locations. Selected bundles cannot borrow models.
 std::string legacyPath(const std::string& path) const {
  if(state_==SelectionState::Legacy)return path;
  if(path.compare(0,13,"/sdcard/html/")==0)
   return resolve(path.substr(8),path);
  if(path=="/sdcard/config/polar-int8.tflite")
   return resolve("model/polar-int8.tflite",path);
  if(path=="/sdcard/config/polar-runtime-frame.rgb")
   return resolve("diagnostics/polar-runtime-frame.rgb",path);
  if(path=="/sdcard/config/polar-runtime-frame.jpg")
   return resolve("diagnostics/polar-runtime-frame.jpg",path);
  if(path=="/sdcard/config/polar-jpeg-vectors.bin")
   return resolve("diagnostics/polar-jpeg-vectors.bin",path);
  if(path=="/sdcard/config/polar-runtime-vectors.bin")
   return resolve("diagnostics/polar-runtime-vectors.bin",path);
  return path;
 }
 // Index is keyed by running application digest, never a shared "current"
 // pointer. A rollback can therefore find the previous application's bundle.
 // Caller chooses required=true for managed installs; only an explicitly
 // optional, missing index permits legacy assets. No directory is created.
 template<class Hash> bool loadForApp(const std::string& base,
       const std::string& appHash,const std::string& modelHash,bool required,
       const std::map<std::string,File>& requiredAssets={}) {
  if(attempted_)return false;
  auto rejected=[this](){attempted_=true;state_=SelectionState::Rejected;return false;};
  if(!hashValid(appHash)||!hashValid(modelHash))return rejected();
  const std::string index=base+"/apps/"+appHash+".id";
  struct stat st{};
  if(stat(index.c_str(),&st)!=0){
   if(errno==ENOENT&&!required&&requiredAssets.empty()){attempted_=true;return true;}
   return rejected();
  }
  if(!S_ISREG(st.st_mode)||(st.st_size!=64&&st.st_size!=65))return rejected();
  FILE* file=std::fopen(index.c_str(),"rb");
  if(!file)return rejected();
  char bytes[66];const size_t n=std::fread(bytes,1,sizeof(bytes),file);
  bool ok=!std::ferror(file)&&n==static_cast<size_t>(st.st_size);
  if(std::fclose(file)!=0)ok=false;
  if(!ok||(n==65&&bytes[64]!='\n'))return rejected();
  const std::string id(bytes,64);
  if(!hashValid(id))return rejected();
  return load<Hash>(base+"/objects/"+id,id,appHash,modelHash,requiredAssets);
 }
 std::string resolve(const std::string& asset,const std::string& legacy) const {
  if(state_==SelectionState::Legacy)return legacy;
  if(state_!=SelectionState::Selected||!manifest_.assets.count(asset))return "";
  return root_+"/"+asset;
 }
};
}
