#pragma once
#include <sys/stat.h>
#include <cerrno>
#include <cstdio>
#include <string>

namespace MeterBundle {
enum class PendingRecovery { Ready, Conflict, IoError };
// Caller holds exclusive update ownership and has validated the bundle ID.
// Preserve interrupted work; never remove files or reuse partially written data.
inline PendingRecovery preparePending(const std::string& base,const std::string& id) {
 const std::string pending=base+"/pending/"+id;
 if(mkdir(pending.c_str(),0700)==0)return PendingRecovery::Ready;
 if(errno!=EEXIST)return PendingRecovery::IoError;
 struct stat st{};
 if(stat(pending.c_str(),&st)!=0)return PendingRecovery::IoError;
 if(!S_ISDIR(st.st_mode))return PendingRecovery::Conflict;
 const std::string retained=base+"/interrupted";
 if(mkdir(retained.c_str(),0700)!=0&&errno!=EEXIST)return PendingRecovery::IoError;
 if(stat(retained.c_str(),&st)!=0||!S_ISDIR(st.st_mode))return PendingRecovery::IoError;
 for(unsigned slot=0;slot<32;++slot) {
  const std::string saved=retained+"/"+id+"-"+std::to_string(slot);
  if(stat(saved.c_str(),&st)==0)continue;
  if(errno!=ENOENT)return PendingRecovery::IoError;
  // Exclusive installer ownership prevents competing destination creation.
  if(std::rename(pending.c_str(),saved.c_str())!=0)return PendingRecovery::IoError;
  return mkdir(pending.c_str(),0700)==0?PendingRecovery::Ready:PendingRecovery::IoError;
 }
 return PendingRecovery::Conflict;
}
}
