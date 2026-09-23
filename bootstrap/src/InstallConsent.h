#pragma once
namespace AIEdgeSetup {
constexpr int readyToInstall = 7;
inline bool mayConfigureWifi(int phase) {
    return phase <= 0 || phase == readyToInstall;
}
inline bool mayInstall(int phase, bool sdReady, bool connected, bool wifiSaved) {
    const bool retryable = phase == -3 || phase == -4 || phase == -5 || phase == -6 || phase == -7;
    return sdReady && connected && wifiSaved && (phase == readyToInstall || retryable);
}
}
