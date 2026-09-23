#pragma once
#include "ArchivePath.h"
#include <map>
#include <cstdint>

class ArchiveInventory {
    std::map<std::string,bool> paths;
    uint64_t expanded=0;
public:
    static constexpr unsigned maximumEntries=512;
    static constexpr uint64_t maximumFileBytes=2*1024*1024;
    static constexpr uint64_t maximumExpandedBytes=32*1024*1024;
    bool add(std::string name,bool directory,uint64_t bytes) {
        if(paths.size()>=maximumEntries || name.size()>200 || !safeArchivePath(name) ||
           bytes>maximumFileBytes || bytes>maximumExpandedBytes-expanded)return false;
        if(directory && name.back()=='/')name.pop_back();
        if(name.empty() || name.back()=='/')return false;
        // Package paths are ASCII. Reject FAT aliases rather than guessing
        // filesystem-specific Unicode folding or trailing-dot normalization.
        for(char& c:name) {
            if(static_cast<unsigned char>(c)>126 || c=='*' || c=='?' || c=='"' || c=='<' || c=='>' || c=='|')return false;
            if(c>='A'&&c<='Z')c+=('a'-'A');
        }
        size_t begin=0;
        while(begin<name.size()) {
            const size_t end=name.find('/',begin);
            const size_t last=(end==std::string::npos?name.size():end)-1;
            if(name[last]=='.'||name[last]==' ')return false;
            if(end==std::string::npos)break;
            begin=end+1;
        }
        if(paths.count(name))return false;
        for(const auto& entry:paths) {
            if(!entry.second && name.compare(0,entry.first.size()+1,entry.first+"/")==0)return false;
            if(!directory && entry.first.compare(0,name.size()+1,name+"/")==0)return false;
        }
        paths.emplace(name,directory);expanded+=bytes;return true;
    }
};
