#pragma once
#include "DeviceBundleManifest.h"
#include <cstdio>
#include <memory>
#include <new>
#include <sys/stat.h>
namespace MeterBundle {
using Checkpoint=void (*)(const char*,const char*,uint64_t);
inline void checkpoint(Checkpoint trace,const char* step,const std::string& path,uint64_t offset=0){if(trace)trace(step,path.c_str(),offset);}
struct Verification {bool verified=false;uint32_t files=0;uint64_t bytes=0;std::string failedPath;};
template<class Hash> bool verifyFile(const std::string& path,const File& expected,Checkpoint trace=nullptr){
 checkpoint(trace,"stat.begin",path);
 struct stat st{};
 if(stat(path.c_str(),&st)!=0||!S_ISREG(st.st_mode)||st.st_size<0||static_cast<uint64_t>(st.st_size)!=expected.bytes)return false;
 checkpoint(trace,"open.begin",path);
 FILE* input=std::fopen(path.c_str(),"rb");if(!input)return false;
 checkpoint(trace,"hash.init",path);
 Hash hash;std::unique_ptr<unsigned char[]> buffer(new(std::nothrow) unsigned char[4096]);
 if(!buffer){std::fclose(input);return false;}
 uint64_t total=0;bool ok=true;
 while(true){checkpoint(trace,"read.begin",path,total);const size_t n=std::fread(buffer.get(),1,4096,input);
  checkpoint(trace,"hash.begin",path,total);
  if(total+n>expected.bytes||!hash.update(buffer.get(),n)){ok=false;break;}
  checkpoint(trace,"block.done",path,total);total+=n;
  if(n<4096){if(std::ferror(input))ok=false;break;}
 }
 checkpoint(trace,"close.begin",path,total);
 if(std::fclose(input)!=0)ok=false;
 checkpoint(trace,"hash.finish",path,total);
 const bool valid=ok&&total==expected.bytes&&hash.finish()==expected.hash;
 checkpoint(trace,valid?"verify.pass":"verify.fail",path,total);
 return valid;
}
// Exclusive updater ownership of a trusted staging tree is required throughout
// verification and subsequent use. This function reads only; it never activates.
template<class Hash> Verification verify(const std::string& root,const std::string& expectedId,Manifest& manifest,Checkpoint trace=nullptr){
 manifest=Manifest{};Verification report;report.failedPath="device-manifest.json";
 if(!hashValid(expectedId))return report;
 const auto path=root+"/device-manifest.json";struct stat st{};
 checkpoint(trace,"manifest.begin",path);
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
 if(!verifyFile<Hash>(root+"/"+report.failedPath,parsed.firmware,trace))return report;
 ++report.files;report.bytes+=parsed.firmware.bytes;
 for(const auto& item:parsed.assets){report.failedPath=item.first;
  if(!verifyFile<Hash>(root+"/"+item.first,item.second,trace))return report;
  ++report.files;report.bytes+=item.second.bytes;
 }
 manifest=parsed;report.failedPath.clear();report.verified=true;return report;
}
}
