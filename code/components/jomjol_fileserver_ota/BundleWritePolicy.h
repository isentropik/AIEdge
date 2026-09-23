#pragma once
#include <string>
namespace MeterBundle {
// Reject ambiguous FAT paths instead of trying to normalize them. Generic file
// operations may not modify the application-managed bundle namespace.
inline bool genericWriteAllowed(const std::string& path) {
 if(path.size()<9||path.compare(0,8,"/sdcard/")!=0)return false;
 size_t start=8;bool first=true;
 while(start<path.size()){
  size_t end=path.find('/',start);if(end==std::string::npos)end=path.size();
  std::string part=path.substr(start,end-start);
  if(part.empty()||part=="."||part==".."||part.back()=='.'||part.back()==' ')return false;
  for(char& c:part){
   const unsigned char u=static_cast<unsigned char>(c);
   if(u<32||u>=127||c=='\\'||c=='%'||c==':'||c=='~')return false;
   if(c>='A'&&c<='Z')c=char(c-'A'+'a');
  }
  if(first&&part=="bundles")return false;
  first=false;start=end+1;
 }
 return true;
}
}
