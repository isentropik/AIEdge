#pragma once
#include <string>
#include <cstdio>
#include <cstring>
#include <cerrno>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
namespace AIEdge {
// Only called after selecting a verified managed bundle. Never replace config.
inline bool seedSetupConfig(const std::string& root) {
 const std::string dir=root+"/config", final=dir+"/config.ini", pending=dir+"/aiedge-first-boot.pending";
 struct stat st{};
 if(stat(final.c_str(),&st)==0)return S_ISREG(st.st_mode);
 if(errno!=ENOENT)return false;
 if(mkdir(dir.c_str(),0755)!=0&&errno!=EEXIST)return false;
 const char data[]="; AIEdge first boot: no recognition or external publication enabled\n"
 "[TakeImage]\nLEDIntensity = 0\nWaitBeforeTakingPicture = 2\n"
 "[AutoTimer]\nInterval = 0.5\n"
 "[Debug]\nLogLevel = 2\nLogfilesRetention = 3\n"
 "[System]\nSetupMode = true\nHostname = aiedge\nCPUFrequency = 160\nTooltip = true\n";
 int flags=O_CREAT|O_EXCL|O_WRONLY;
#ifdef O_BINARY
 flags|=O_BINARY;
#endif
 int fd=open(pending.c_str(),flags,0600);if(fd<0)return false;
 bool ok=write(fd,data,sizeof(data)-1)==sizeof(data)-1;
 if(ok&&fsync(fd)!=0)ok=false;
 if(close(fd)!=0)ok=false;
 char readback[sizeof(data)]={};FILE* f=fopen(pending.c_str(),"rb");
 if(!f)return false;
 const size_t count=fread(readback,1,sizeof readback,f);
 if(ferror(f)||count!=sizeof(data)-1||memcmp(readback,data,sizeof(data)-1))ok=false;
 if(fclose(f)!=0)ok=false;
 if(!ok)return false;
 if(stat(final.c_str(),&st)==0||errno!=ENOENT)return false;
 return rename(pending.c_str(),final.c_str())==0;
}
}
