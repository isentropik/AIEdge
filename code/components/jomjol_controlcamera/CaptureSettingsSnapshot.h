#pragma once
#include <string>

namespace CaptureSettingsSnapshot {
// Deterministic, versioned descriptor of reported/configured state, not a claim
// of hardware register readback or physical illumination measurement.
template<class Driver,class Config>
std::string encode(const Driver& driver,const Config& config,int duty,int delayMs,const std::string& lighting) {
    if(lighting.empty() || lighting.size()>4096)return "";
    std::string s="capture-settings-v1\nsource=driver-status-and-capture-config\n";
#define DRIVER_FIELD(name) s+="driver." #name "="+std::to_string(static_cast<long long>(driver.name))+"\n";
    DRIVER_FIELD(framesize) DRIVER_FIELD(scale) DRIVER_FIELD(binning) DRIVER_FIELD(quality)
    DRIVER_FIELD(brightness) DRIVER_FIELD(contrast) DRIVER_FIELD(saturation) DRIVER_FIELD(sharpness)
    DRIVER_FIELD(denoise) DRIVER_FIELD(special_effect) DRIVER_FIELD(wb_mode) DRIVER_FIELD(awb)
    DRIVER_FIELD(awb_gain) DRIVER_FIELD(aec) DRIVER_FIELD(aec2) DRIVER_FIELD(ae_level)
    DRIVER_FIELD(aec_value) DRIVER_FIELD(agc) DRIVER_FIELD(agc_gain) DRIVER_FIELD(gainceiling)
    DRIVER_FIELD(bpc) DRIVER_FIELD(wpc) DRIVER_FIELD(raw_gma) DRIVER_FIELD(lenc)
    DRIVER_FIELD(hmirror) DRIVER_FIELD(vflip) DRIVER_FIELD(dcw) DRIVER_FIELD(colorbar)
#undef DRIVER_FIELD
#define CONFIG_FIELD(name) s+="config." #name "="+std::to_string(static_cast<long long>(config.name))+"\n";
    CONFIG_FIELD(CamSensor_id) CONFIG_FIELD(ImageWidth) CONFIG_FIELD(ImageHeight)
    CONFIG_FIELD(ImageZoomEnabled) CONFIG_FIELD(ImageZoomOffsetX) CONFIG_FIELD(ImageZoomOffsetY)
    CONFIG_FIELD(ImageZoomSize) CONFIG_FIELD(ImageAutoSharpness) CONFIG_FIELD(ImageLedIntensity)
    CONFIG_FIELD(DemoMode)
#undef CONFIG_FIELD
    s+="master-duty="+std::to_string(duty)+"\nflash-delay-ms="+std::to_string(delayMs)+"\n";
    return s+lighting;
}
}
