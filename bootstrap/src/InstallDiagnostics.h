#pragma once
#include <cstdio>
#include <cstring>
#include <string>
#include <cstdint>
namespace AIEdgeSetup {
// Bounded RAM journal. Caller supplies synchronization; never accesses the SD.
class InstallJournal {
    static constexpr size_t capacity=96, width=256;
    char lines[capacity][width]{};
    size_t next=0,count=0;
    char operation[176]="idle";
    uint32_t since=0;
public:
    void current(const char* step,const char* path,uint64_t offset,uint32_t now){
        std::snprintf(operation,sizeof operation,"%s %s offset=%llu",step,path,(unsigned long long)offset);
        since=now;
    }
    const char* active() const{return operation;}
    uint32_t age(uint32_t now) const{return now-since;}
    void append(const char* line){std::snprintf(lines[next],width,"%s",line);next=(next+1)%capacity;if(count<capacity)++count;}
    std::string snapshot() const{
        std::string out="AIEdge loader debug log. Times are milliseconds since boot. RAM history resets on restart. Oldest entries may be overwritten.\n";
        for(size_t i=0;i<count;++i){out+=lines[(next+capacity-count+i)%capacity];out+='\n';}
        return out;
    }
};
}
