#pragma once
#include "MeterCumulative.h"
#include "ConfigJournal.h"
#include <cstring>

namespace meter {
struct Checkpoint {
    Frame reference{};
    Bounds bounds;
    bool hasSegment=false;
    Frame anchor{};
    double minimumFt3=0;
    std::string modelHash,calibrationHash;
};
inline bool hashIdentity(const std::string& text) {
    if(text.size()!=64)return false;
    for(char c:text)if(!((c>='0'&&c<='9')||(c>='a'&&c<='f')))return false;
    return true;
}
inline bool checkpointSegment(const Checkpoint& value,CumulativeResult& out) {
    if(!value.hasSegment)return false;
    const auto& a=value.anchor;const auto& f=value.reference;
    if(!a.captureTimeValid||a.captureUs<=0||a.clockId!=f.clockId||a.captureUs>f.captureUs||
       !consistent(a.main,value.bounds.mainDial)||!validPosition(a.secondary)||
       !std::isfinite(value.minimumFt3)||value.minimumFt3<0)return false;
    Cumulative rebuilt;rebuilt.reset(a);
    if(a.captureUs==f.captureUs){
        for(int i=0;i<5;++i)if(a.main[i]!=f.main[i])return false;
        if(a.secondary!=f.secondary||value.minimumFt3!=0)return false;
    } else if(!rebuilt.observe(f,value.bounds))return false;
    out=rebuilt.current();
    if(value.minimumFt3<out.minimumFt3||value.minimumFt3>out.maximumFt3)return false;
    out.minimumFt3=value.minimumFt3;
    if(std::isfinite(out.estimatedFt3)&&out.estimatedFt3<out.minimumFt3){
        out.estimatedFt3=std::numeric_limits<double>::quiet_NaN();out.status=Status::BoundedOnly;
    }
    return true;
}
inline bool checkpointValid(const Checkpoint& value) {
    const auto& b=value.bounds;const auto& f=value.reference;
    CumulativeResult segment;
    return (!value.hasSegment||checkpointSegment(value,segment))&&hashIdentity(value.modelHash)&&hashIdentity(value.calibrationHash)&&
        std::isfinite(b.mainDial)&&b.mainDial>=0&&b.mainDial<.5&&
        std::isfinite(b.secondaryDial)&&b.secondaryDial>=0&&b.secondaryDial<.5&&
        std::isfinite(b.maximumRateFt3S)&&b.maximumRateFt3S>=0&&
        f.captureTimeValid&&f.captureUs>0&&f.clockId&&
        consistent(f.main,b.mainDial)&&validPosition(f.secondary);
}
inline void append64(std::string& out,uint64_t value) {
    for(int i=0;i<8;++i)out.push_back(static_cast<char>(value>>(8*i)));
}
inline uint64_t read64(const std::string& bytes,size_t offset) {
    uint64_t value=0;
    for(int i=0;i<8;++i)value|=uint64_t(static_cast<unsigned char>(bytes[offset+i]))<<(8*i);
    return value;
}
inline void appendDouble(std::string& out,double value) {
    static_assert(sizeof(double)==8&&std::numeric_limits<double>::is_iec559,"IEEE binary64 required");
    uint64_t bits;std::memcpy(&bits,&value,8);append64(out,bits);
}
inline double readDouble(const std::string& bytes,size_t offset) {
    const uint64_t bits=read64(bytes,offset);double value;std::memcpy(&value,&bits,8);return value;
}
inline std::string encodeCheckpoint(const Checkpoint& value) {
    if(!checkpointValid(value))return {};
    std::string bytes=value.hasSegment?"MTRC0002":"MTRC0001";
    bytes+=value.modelHash;bytes+=value.calibrationHash;
    for(double dial:value.reference.main)appendDouble(bytes,dial);
    appendDouble(bytes,value.reference.secondary);
    append64(bytes,static_cast<uint64_t>(value.reference.captureUs));append64(bytes,value.reference.clockId);
    appendDouble(bytes,value.bounds.mainDial);appendDouble(bytes,value.bounds.secondaryDial);
    appendDouble(bytes,value.bounds.maximumRateFt3S);bytes.push_back(value.bounds.hasMaximumRate?1:0);
    if(value.hasSegment){
        for(double dial:value.anchor.main)appendDouble(bytes,dial);
        appendDouble(bytes,value.anchor.secondary);append64(bytes,value.anchor.captureUs);
        append64(bytes,value.anchor.clockId);appendDouble(bytes,value.minimumFt3);
    }
    ConfigJournal::append32(bytes,ConfigJournal::crc(bytes));return bytes;
}
inline bool decodeCheckpoint(const std::string& bytes,const std::string& modelHash,
                             const std::string& calibrationHash,const Bounds& bounds,Checkpoint& output) {
    const bool v2=bytes.size()==301&&bytes.compare(0,8,"MTRC0002")==0;
    if((!v2&&(bytes.size()!=229||bytes.compare(0,8,"MTRC0001")))||
       ConfigJournal::crc(bytes.substr(0,bytes.size()-4))!=ConfigJournal::get32(bytes,bytes.size()-4))return false;
    Checkpoint value;value.modelHash=bytes.substr(8,64);value.calibrationHash=bytes.substr(72,64);
    if(value.modelHash!=modelHash||value.calibrationHash!=calibrationHash)return false;
    for(int i=0;i<5;++i)value.reference.main[i]=readDouble(bytes,136+i*8);
    value.reference.secondary=readDouble(bytes,176);
    const uint64_t time=read64(bytes,184);
    if(time>static_cast<uint64_t>(std::numeric_limits<int64_t>::max()))return false;
    value.reference.captureUs=static_cast<int64_t>(time);value.reference.clockId=read64(bytes,192);
    value.reference.captureTimeValid=true;
    value.bounds.mainDial=readDouble(bytes,200);value.bounds.secondaryDial=readDouble(bytes,208);
    value.bounds.maximumRateFt3S=readDouble(bytes,216);
    if(bytes[224]!=0&&bytes[224]!=1)return false;
    value.bounds.hasMaximumRate=bytes[224]==1;
    if(v2){
        value.hasSegment=true;
        for(int i=0;i<5;++i)value.anchor.main[i]=readDouble(bytes,225+i*8);
        value.anchor.secondary=readDouble(bytes,265);
        const uint64_t anchorTime=read64(bytes,273);
        if(anchorTime>static_cast<uint64_t>(std::numeric_limits<int64_t>::max()))return false;
        value.anchor.captureUs=static_cast<int64_t>(anchorTime);value.anchor.clockId=read64(bytes,281);
        value.anchor.captureTimeValid=true;value.minimumFt3=readDouble(bytes,289);
    }
    if(value.bounds.mainDial!=bounds.mainDial||value.bounds.secondaryDial!=bounds.secondaryDial||
       value.bounds.hasMaximumRate!=bounds.hasMaximumRate||value.bounds.maximumRateFt3S!=bounds.maximumRateFt3S||
       !checkpointValid(value))return false;
    output=value;return true;
}
}
