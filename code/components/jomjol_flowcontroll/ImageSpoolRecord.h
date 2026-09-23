#pragma once
#include "ImageArchiveMetadata.h"

namespace ImageArchive {
// Versioned fixed-size sidecar. No struct layout, pointers, padding, machine
// endianness, floating-point timestamp or retry-clock state is persisted.
static constexpr size_t SpoolBodyBytes = 496;
static constexpr size_t SpoolRecordBytes = SpoolBodyBytes + 64;
inline void appendInteger(std::string& bytes, uint64_t value, unsigned width) {
    for(unsigned i=0;i<width;++i) bytes.push_back(static_cast<char>((value>>(i*8))&255));
}
inline uint64_t spoolInteger(const std::string& bytes, size_t offset, unsigned width) {
    uint64_t value=0;
    for(unsigned i=0;i<width;++i) value|=static_cast<uint64_t>(static_cast<unsigned char>(bytes[offset+i]))<<(i*8);
    return value;
}
inline void appendField(std::string& bytes, const std::string& value, size_t width) {
    bytes+=value;bytes.append(width-value.size(),'\0');
}
inline bool spoolField(const std::string& bytes, size_t offset, size_t width, std::string& value) {
    const auto end=bytes.find('\0',offset);
    if(end==std::string::npos || end>=offset+width) return false;
    for(size_t n=end;n<offset+width;++n) if(bytes[n]!='\0') return false;
    value=bytes.substr(offset,end-offset);
    return true;
}
template<class Sha256>
std::string encodeSpoolRecord(const CaptureMetadata& m, Sha256 sha) {
    if(!validMetadata(m)) return "";
    std::string bytes="IMGSPL01";
    appendInteger(bytes,m.captureUs,8);appendInteger(bytes,m.imageBytes,4);
    appendField(bytes,m.device,65);appendField(bytes,m.boot,65);appendField(bytes,m.captureUtc,21);
    for(const auto* value:{&m.imageHash,&m.firmwareHash,&m.modelHash,&m.calibrationHash,&m.settingsHash})
        appendField(bytes,*value,65);
    if(bytes.size()!=SpoolBodyBytes) return "";
    const auto hash=sha(bytes);
    return validHash(hash) ? bytes+hash : "";
}
template<class Sha256>
bool decodeSpoolRecord(const std::string& bytes, Sha256 sha, CaptureMetadata& out) {
    out=CaptureMetadata{};
    if(bytes.size()!=SpoolRecordBytes || bytes.compare(0,8,"IMGSPL01")!=0) return false;
    const auto hash=sha(bytes.substr(0,SpoolBodyBytes));
    if(!validHash(hash) || hash!=bytes.substr(SpoolBodyBytes)) return false;
    CaptureMetadata m;
    m.captureUs=spoolInteger(bytes,8,8);m.imageBytes=static_cast<uint32_t>(spoolInteger(bytes,16,4));
    if(!spoolField(bytes,20,65,m.device) || !spoolField(bytes,85,65,m.boot) ||
       !spoolField(bytes,150,21,m.captureUtc)) return false;
    size_t offset=171;
    for(auto* value:{&m.imageHash,&m.firmwareHash,&m.modelHash,&m.calibrationHash,&m.settingsHash}) {
        if(!spoolField(bytes,offset,65,*value)) return false;
        offset+=65;
    }
    if(!validMetadata(m)) return false;
    out=m;
    return true;
}
} // namespace ImageArchive
