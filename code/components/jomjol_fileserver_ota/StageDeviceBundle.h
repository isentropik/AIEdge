#pragma once
#include "VerifyDeviceBundle.h"
#include "miniz/miniz.h"
#include <fcntl.h>
#include <unistd.h>
#include <cerrno>
#include <cstring>
namespace MeterBundle {
enum class StageResult { Rejected, IoError, Conflict, Existing, Staged };
// The convenience extract functions put the large inflater on the task stack.
// The iterator keeps it on the heap and retains miniz's length/CRC checks.
template<class Sink> bool extractBounded(mz_zip_archive& zip,mz_uint index,uint64_t expected,Sink sink){
 auto* iterator=mz_zip_reader_extract_iter_new(&zip,index,0);
 if(!iterator)return false;
 std::unique_ptr<unsigned char[]> buffer(new(std::nothrow) unsigned char[4096]);
 uint64_t total=0;bool ok=bool(buffer);
 while(ok){
  const size_t n=mz_zip_reader_extract_iter_read(iterator,buffer.get(),4096);
  if(!n)break;
  if(total>expected||n>expected-total||!sink(total,buffer.get(),n)){ok=false;break;}
  total+=n;
 }
 // Always free; finalization also rejects truncated output and CRC failures.
 const bool complete=mz_zip_reader_extract_iter_free(iterator)!=0;
 return ok&&complete&&total==expected;
}
inline bool bundleDirectory(const std::string& path){
 if(mkdir(path.c_str(),0700)!=0&&errno!=EEXIST)return false;
 struct stat st{};return stat(path.c_str(),&st)==0&&S_ISDIR(st.st_mode);
}
inline bool bundleParents(const std::string& root,const std::string& name){
 size_t at=0;
 while((at=name.find('/',at))!=std::string::npos){
  if(!bundleDirectory(root+"/"+name.substr(0,at)))return false;
  ++at;
 }
 return true;
}
template<class Hash> struct BundleSink {
 int fd;uint64_t written=0,limit;Hash hash;bool ok=true;
 Checkpoint trace;std::string path;
 BundleSink(int f,uint64_t size,Checkpoint cb=nullptr,const std::string& name=""):fd(f),limit(size),trace(cb),path(name){}
 static size_t append(void* opaque,mz_uint64 offset,const void* data,size_t size){
  auto& self=*static_cast<BundleSink*>(opaque);
  if(!self.ok||offset!=self.written||self.written>self.limit||size>self.limit-self.written){self.ok=false;return 0;}
  checkpoint(self.trace,"extract.write",self.path,self.written);
  if(size && (write(self.fd,data,size)!=static_cast<ssize_t>(size)||
     !self.hash.update(static_cast<const unsigned char*>(data),size))){self.ok=false;return 0;}
  self.written+=size;return size;
 }
};
// Only from the exclusive managed installer. Never writes current HTML, apps
// indexes, flash, or existing objects. Failed pending directories are retained.
template<class Hash> StageResult stageZip(const std::string& zipPath,const std::string& base,
 const std::string& id,const std::string& model,Checkpoint trace=nullptr){
 checkpoint(trace,"archive.open",zipPath);
 if(!hashValid(id)||!hashValid(model))return StageResult::Rejected;
 mz_zip_archive zip{};
 if(!mz_zip_reader_init_file(&zip,zipPath.c_str(),0))return StageResult::Rejected;
 struct CloseZip {mz_zip_archive* p;void close(){if(p){mz_zip_reader_end(p);p=nullptr;}}~CloseZip(){close();}} closeZip{&zip};
 const auto count=mz_zip_reader_get_num_files(&zip);
 if(!count||count>ArchiveInventory::maximumEntries)return StageResult::Rejected;
 ArchiveInventory inventory;std::map<std::string,mz_uint> entries;
 for(mz_uint i=0;i<count;++i){mz_zip_archive_file_stat st{};
  if(!mz_zip_reader_file_stat(&zip,i,&st)||st.m_is_directory||st.m_is_encrypted||!st.m_is_supported||
     !inventory.add(st.m_filename,false,st.m_uncomp_size))return StageResult::Rejected;
  entries.emplace(st.m_filename,i);
 }
 const auto found=entries.find("device-manifest.json");
 if(found==entries.end())return StageResult::Rejected;
 mz_zip_archive_file_stat ms{};
 if(!mz_zip_reader_file_stat(&zip,found->second,&ms)||!ms.m_uncomp_size||ms.m_uncomp_size>128*1024)return StageResult::Rejected;
 std::unique_ptr<char[]> bytes(new(std::nothrow) char[ms.m_uncomp_size]);
 if(!bytes)return StageResult::IoError;
 if(!extractBounded(zip,found->second,ms.m_uncomp_size,[&](uint64_t offset,const unsigned char* data,size_t size){
  std::memcpy(bytes.get()+offset,data,size);return true;
 }))return StageResult::Rejected;
 std::string body(bytes.get(),ms.m_uncomp_size);bytes.reset();
 auto sha=[](const std::string& text){Hash h;return h.update(reinterpret_cast<const unsigned char*>(text.data()),text.size())?h.finish():std::string();};
 Manifest m;
 if(!parse(body,m,sha)||m.id!=id||m.bootPolicy!="required_bundle"||m.modelHash!=model)return StageResult::Rejected;
 auto wanted=m.assets;wanted.emplace("firmware/firmware.bin",m.firmware);
 File manifestFile;manifestFile.bytes=body.size();manifestFile.hash=sha(body);
 wanted.emplace("device-manifest.json",manifestFile);
 // Parsed fields own their strings. Release redundant manifest/inventory copies
 // before extraction and FAT readback need internal DMA-capable memory.
 std::string().swap(body);m=Manifest{};inventory=ArchiveInventory{};
 for(const auto& item:wanted){auto e=entries.find(item.first);mz_zip_archive_file_stat st{};
  if(e==entries.end()||!mz_zip_reader_file_stat(&zip,e->second,&st)||st.m_uncomp_size!=item.second.bytes)return StageResult::Rejected;
 }
 const std::string object=base+"/objects/"+id,pending=base+"/pending/"+id;
 struct stat st{};
 if(stat(object.c_str(),&st)==0){
  entries.clear();wanted.clear();closeZip.close();Manifest existing;
  return S_ISDIR(st.st_mode)&&verify<Hash>(object,id,existing,trace).verified?StageResult::Existing:StageResult::Conflict;
 }
 if(errno!=ENOENT)return StageResult::IoError;
 if(!bundleDirectory(base)||!bundleDirectory(base+"/objects")||!bundleDirectory(base+"/pending")||
    !bundleDirectory(base+"/apps"))return StageResult::IoError;
 if(mkdir(pending.c_str(),0700)!=0)return errno==EEXIST?StageResult::Conflict:StageResult::IoError;
 for(const auto& item:wanted){
  if(!bundleParents(pending,item.first))return StageResult::IoError;
  int flags=O_WRONLY|O_CREAT|O_EXCL;
#ifdef O_BINARY
  flags|=O_BINARY;
#endif
  const std::string path=pending+"/"+item.first;int fd=open(path.c_str(),flags,0600);
  if(fd<0)return StageResult::IoError;
  checkpoint(trace,"extract.begin",path);
  BundleSink<Hash> sink(fd,item.second.bytes,trace,path);
  bool ok=extractBounded(zip,entries.at(item.first),item.second.bytes,[&](uint64_t offset,const unsigned char* data,size_t size){
           return BundleSink<Hash>::append(&sink,offset,data,size)==size;
          })&&
          sink.ok&&sink.written==item.second.bytes&&sink.hash.finish()==item.second.hash;
  checkpoint(trace,"extract.sync",path,sink.written);
  if(ok&&fsync(fd)!=0)ok=false;
  if(close(fd)!=0)ok=false;
  if(!ok||!verifyFile<Hash>(path,item.second,trace))return StageResult::IoError;
 }
 entries.clear();wanted.clear();closeZip.close();
 Manifest verified;if(!verify<Hash>(pending,id,verified,trace).verified)return StageResult::Rejected;
 if(stat(object.c_str(),&st)==0)return StageResult::Conflict;
 if(errno!=ENOENT||std::rename(pending.c_str(),object.c_str())!=0)return StageResult::IoError;
 return StageResult::Staged;
}
}
