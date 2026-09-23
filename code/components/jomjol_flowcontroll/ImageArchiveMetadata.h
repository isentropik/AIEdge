#pragma once
#include "ImageUploadQueue.h"

namespace ImageArchive {
struct CaptureMetadata {
    std::string device, boot, imageHash, firmwareHash, modelHash, calibrationHash, settingsHash;
    uint64_t captureUs = 0;
    uint32_t imageBytes = 0;
    // Empty means unknown. Do not substitute upload/retrieval time.
    std::string captureUtc;
};
inline bool validName(const std::string& s) {
    if (s.empty() || s.size() > 64) return false;
    for (char c : s) if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                           (c >= '0' && c <= '9') || c == '_' || c == '-')) return false;
    return true;
}
inline int decimalAt(const std::string& s, size_t at, size_t count) {
    int value=0;
    for(size_t i=at;i<at+count;++i) {
        if(s[i]<'0'||s[i]>'9') return -1;
        value=value*10+s[i]-'0';
    }
    return value;
}
inline bool validUtc(const std::string& s) {
    if(s.empty()) return true;
    // Emit an intentionally narrow canonical UTC format; no offsets or fractions.
    if(s.size()!=20 || s[4]!='-' || s[7]!='-' || s[10]!='T' || s[13]!=':' || s[16]!=':' || s[19]!='Z') return false;
    const int year=decimalAt(s,0,4), month=decimalAt(s,5,2), day=decimalAt(s,8,2);
    const int hour=decimalAt(s,11,2), minute=decimalAt(s,14,2), second=decimalAt(s,17,2);
    if(year<1||month<1||month>12||day<1||hour<0||hour>23||minute<0||minute>59||second<0||second>59) return false;
    const int days[]={31,28,31,30,31,30,31,31,30,31,30,31};
    const bool leap=year%4==0 && (year%100!=0 || year%400==0);
    return day<=days[month-1]+(month==2 && leap ? 1:0);
}
inline bool validMetadata(const CaptureMetadata& m) {
    return validName(m.device) && validName(m.boot) && validUtc(m.captureUtc) &&
        m.captureUs<=static_cast<uint64_t>(std::numeric_limits<int64_t>::max()) &&
        m.imageBytes>0 && m.imageBytes<=2*1024*1024 && validHash(m.imageHash) &&
        validHash(m.firmwareHash) && validHash(m.modelHash) &&
        validHash(m.calibrationHash) && validHash(m.settingsHash);
}
// Restricted strings need no escaping. Key order and integer representation
// match the receiver canonical JSON exactly, including capture times above 2^53.
inline std::string metadataJson(const CaptureMetadata& m) {
    if(!validMetadata(m)) return "";
    return "{\"boot_id\":\""+m.boot+"\",\"calibration_sha256\":\""+m.calibrationHash+
        "\",\"capture_us\":"+std::to_string(m.captureUs)+",\"capture_utc\":"+
        (m.captureUtc.empty() ? "null" : "\""+m.captureUtc+"\"")+",\"device_id\":\""+m.device+
        "\",\"firmware_sha256\":\""+m.firmwareHash+"\",\"image_bytes\":"+std::to_string(m.imageBytes)+
        ",\"image_sha256\":\""+m.imageHash+"\",\"model_sha256\":\""+m.modelHash+
        "\",\"settings_sha256\":\""+m.settingsHash+"\",\"version\":1}";
}
struct UploadRecord {
    Identity identity;
    std::string metadata, record;
};
// The caller supplies SHA-256 and must first hash the actual saved image bytes.
// Build into a temporary result so a hashing failure leaves no usable identity.
template<class Sha256>
bool buildRecord(const CaptureMetadata& m, Sha256 sha, UploadRecord& out) {
    out=UploadRecord{};
    UploadRecord r;
    r.metadata=metadataJson(m);
    if(r.metadata.empty()) return false;
    const std::string capture="{\"boot_id\":\""+m.boot+"\",\"capture_us\":"+
        std::to_string(m.captureUs)+",\"device_id\":\""+m.device+"\"}";
    r.identity.capture=sha(capture);
    if(!validHash(r.identity.capture)) return false;
    r.identity.image=m.imageHash; r.identity.bytes=m.imageBytes;
    r.record="{\"capture_id\":\""+r.identity.capture+"\",\"metadata\":"+r.metadata+
        ",\"review_status\":\"unreviewed\",\"training_eligible\":false}";
    r.identity.record=sha(r.record);
    if(!r.identity.valid()) return false;
    out=r;
    return true;
}
} // namespace ImageArchive
