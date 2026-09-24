#pragma once
#include "VerifyDeviceBundle.h"
#include <cerrno>
#include <fcntl.h>
#include <unistd.h>
namespace MeterBundle {
enum class IndexResult { Rejected, Conflict, IoError, Existing, Installed };
inline bool indexEquals(const std::string& path,const std::string& id) {
 FILE* f=std::fopen(path.c_str(),"rb");if(!f)return false;
 char bytes[66];const auto n=std::fread(bytes,1,sizeof(bytes),f);
 bool ok=!std::ferror(f)&&(n==64||(n==65&&bytes[64]=='\n'))&&std::string(bytes,64)==id;
 if(std::fclose(f)!=0)ok=false;
 return ok;
}
// Caller owns trusted base exclusively. Objects must already be staged under
// objects/<id>, and remain immutable. Parents must exist. Never replaces an
// existing mapping, removes failed files, changes boot partition, or reboots.
// fsync/readback does not establish physical SD directory power-loss durability.
template<class Hash> IndexResult prepareIndex(const std::string& base,
 const std::string& id,const std::string& runningApp,const std::string& model) {
 if(!hashValid(runningApp)||!hashValid(model))return IndexResult::Rejected;
 Manifest m;
 if(!verify<Hash>(base+"/objects/"+id,id,m).verified||m.appHash==runningApp||m.modelHash!=model)
  return IndexResult::Rejected;
 const std::string final=base+"/apps/"+m.appHash+".id";
 struct stat st{};
 if(stat(final.c_str(),&st)==0)
  return S_ISREG(st.st_mode)&&indexEquals(final,id)?IndexResult::Existing:IndexResult::Conflict;
 if(errno!=ENOENT)return IndexResult::IoError;
 const std::string pending=final+".pending";
 // A prior interrupted write must not permanently block the same verified app.
 // Preserve it under a bounded diagnostic name; never treat it as a mapping.
 if(stat(pending.c_str(),&st)==0) {
  if(!S_ISREG(st.st_mode))return IndexResult::Conflict;
  bool preserved=false;
  for(unsigned slot=0;slot<32;++slot) {
   const std::string saved=pending+".interrupted-"+std::to_string(slot);
   if(stat(saved.c_str(),&st)==0)continue;
   if(errno!=ENOENT)return IndexResult::IoError;
   if(std::rename(pending.c_str(),saved.c_str())!=0)return IndexResult::IoError;
   preserved=true;break;
  }
  if(!preserved)return IndexResult::Conflict;
 } else if(errno!=ENOENT)return IndexResult::IoError;
 int flags=O_WRONLY|O_CREAT|O_EXCL;
#ifdef O_BINARY
 flags|=O_BINARY;
#endif
 int fd=open(pending.c_str(),flags,0600);
 if(fd<0)return IndexResult::IoError;
 const std::string body=id+"\n";
 bool ok=write(fd,body.data(),body.size())==static_cast<ssize_t>(body.size());
 if(ok&&fsync(fd)!=0)ok=false;
 if(close(fd)!=0)ok=false;
 if(!ok||!indexEquals(pending,id))return IndexResult::IoError;
 // Exclusive ownership is required: POSIX rename may overwrite, so recheck.
 if(stat(final.c_str(),&st)==0)return IndexResult::Conflict;
 if(errno!=ENOENT)return IndexResult::IoError;
 if(std::rename(pending.c_str(),final.c_str())!=0||!indexEquals(final,id))return IndexResult::IoError;
 return IndexResult::Installed;
}
}
