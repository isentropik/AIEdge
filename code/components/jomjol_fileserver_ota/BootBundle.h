#pragma once
#include "RuntimeBundle.h"
#include "../jomjol_flowcontroll/ImageArchiveSha.h"
#include "PolarIdentity.h"
#include "PolarModelRoles.h"
#include "esp_ota_ops.h"
#include "esp_partition.h"
namespace MeterBundle {
// Before HTTP/processing tasks and asset presence checks. No SD/flash writes.
inline bool initializeBootBundle(bool required) {
 unsigned char digest[32];
 const auto* partition=esp_ota_get_running_partition();
 std::string identity;
 if(partition && esp_partition_get_sha256(partition,digest)==ESP_OK){
  const char* hex="0123456789abcdef";
  for(unsigned char value:digest){identity+=hex[value>>4];identity+=hex[value&15];}
 }
 std::map<std::string,File> roles;
 for(const auto* spec : {&polar::mainModel,&polar::secondaryModel}){
  File expected;expected.bytes=spec->bytes;expected.hash=spec->hex;roles[spec->asset]=expected;
 }
 return bootSelection().loadForApp<ImageArchive::Sha256>(
  "/sdcard/bundles",identity,polar::modelIdentity,required,roles);
}
}
