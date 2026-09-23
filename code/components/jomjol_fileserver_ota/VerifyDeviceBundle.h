#pragma once
#include "DeviceBundleManifest.h"
#include <cstdio>
#include <memory>
#include <new>
#include <sys/stat.h>
namespace MeterBundle {
struct Verification {bool verified=false;uint32_t files=0;uint64_t bytes=0;std::string failedPath;};
template<class Hash> bool verifyFile(const std::string& path,const File& expected){
 struct stat st{};
 if(stat(path.c_str(),&st)!=0||!S_ISREG(st.st_mode)||st.st_size<0||static_cast<uint64_t>(st.st_size)!=expected.bytes)return false;
 FILE* input=std::fopen(path.c_str(),"rb");if(!input)return false;
 Hash hash;std::unique_ptr<unsigned char[]> buffer(new(std::nothrow) unsigned char[4096]);
 if(!buffer){std::fclose(input);return false;}
 uint64_t total=0;bool ok=true;
 while(true){const size_t n=std::fread(buffer.get(),1,4096,input);
  if(total+n>expected.bytes||!hash.update(buffer.get(),n)){ok=false;break;}total+=n;
  if(n<4096){if(std::ferror(input))ok=false;break;}
 }
 if(std::fclose(input)!=0)ok=false;
 return ok&&total==expected.bytes&&hash.finish()==expected.hash;
}
// Exclusive updater ownership of a trusted staging tree is required throughout
// verification and subsequent use. This function reads only; it never activates.
template<class Hash> Verification verify(const std::string& root,const std::string& expectedId,Manifest& manifest){
 manifest=Manifest{};Verification report;report.failedPath="device-manifest.json";
 if(!hashValid(expectedId))return report;
 const auto path=root+"/device-manifest.json";struct stat st{};
 if(stat(path.c_str(),&st)!=0||!S_ISREG(st.st_mode)||st.st_size<=0||st.st_size>128*1024)return report;
 FILE* input=std::fopen(path.c_str(),"rb");if(!input)return report;
 std::string body;std::unique_ptr<char[]> chunk(new(std::nothrow) char[4096]);
 if(!chunk){std::fclose(input);return report;}
 bool ok=true;
 while(true){const size_t n=std::fread(chunk.get(),1,4096,input);
  if(body.size()+n>128*1024){ok=false;break;}body.append(chunk.get(),n);
  if(n<4096){if(std::ferror(input))ok=false;break;}
 }
 if(std::fclose(input)!=0)ok=false;
 Manifest parsed;
 auto sha=[](const std::string& value){Hash h;if(!h.update(reinterpret_cast<const unsigned char*>(value.data()),value.size()))return std::string();return h.finish();};
 if(!ok||!parse(body,parsed,sha)||parsed.id!=expectedId)return report;
 report.failedPath="firmware/firmware.bin";
 if(!verifyFile<Hash>(root+"/"+report.failedPath,parsed.firmware))return report;
 ++report.files;report.bytes+=parsed.firmware.bytes;
 for(const auto& item:parsed.assets){report.failedPath=item.first;
  if(!verifyFile<Hash>(root+"/"+item.first,item.second))return report;
  ++report.files;report.bytes+=item.second.bytes;
 }
 manifest=parsed;report.failedPath.clear();report.verified=true;return report;
}
}
