#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
namespace AIEdgeAuth {
class SerialParser {
    char line[96]={};size_t used=0;bool discarded=false;
public:
    void reset(){used=0;discarded=false;std::memset(line,0,sizeof line);}
    // A completed binary exchange must not swallow the next console command.
    // Preserve partial printable input when a person pauses while typing.
    void idle(){if(discarded)reset();}
    template<class Dispatch> void feed(uint8_t byte,Dispatch dispatch){
        if(byte=='\r'||byte=='\n'){
            if(!discarded&&used&&std::strncmp(line,"AIEdge AUTH ",12)==0)dispatch(line);
            reset();return;
        }
        if(discarded)return;
        if(byte<0x20||byte>0x7e||used>=sizeof line-1){discarded=true;used=0;return;}
        line[used++]=char(byte);line[used]=0;
    }
};
}
