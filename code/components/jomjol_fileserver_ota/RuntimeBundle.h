#pragma once
#include "BundleSelection.h"
namespace MeterBundle {
// Initialization must finish before any HTTP/processing tasks start. No setter
// is exposed to runtime consumers; boot activation will own initialization.
inline Selection& bootSelection() { static Selection selection; return selection; }
inline std::string runtimePath(const std::string& legacy) {
 return bootSelection().legacyPath(legacy);
}
inline std::string webRoot() {
 const auto& selected=bootSelection();
 if(selected.state()==SelectionState::Legacy)return "/sdcard/html";
 const auto index=selected.resolve("html/index.html","");
 return index.empty()?std::string():index.substr(0,index.size()-11);
}
inline std::string frozenModelPath(const std::string& legacy) {
 return bootSelection().resolve("model/polar-int8.tflite",legacy);
}
}
