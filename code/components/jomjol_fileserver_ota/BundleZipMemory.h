#pragma once
#include "miniz/miniz.h"
#include <cstdint>
#ifdef ESP_PLATFORM
#include "esp_heap_caps.h"
#endif
namespace MeterBundle {
// Keep inflater state, dictionaries and ZIP indexes out of DMA-capable RAM.
// SDMMC still needs an internal bounce buffer when reading into PSRAM.
inline void configureZipMemory(mz_zip_archive& zip){
#ifdef ESP_PLATFORM
 zip.m_pAlloc=[](void*,size_t items,size_t bytes)->void*{
  if(bytes&&items>SIZE_MAX/bytes)return nullptr;
  return heap_caps_malloc(items*bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 };
 zip.m_pRealloc=[](void*,void* previous,size_t items,size_t bytes)->void*{
  if(bytes&&items>SIZE_MAX/bytes)return nullptr;
  return heap_caps_realloc(previous,items*bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
 };
 zip.m_pFree=[](void*,void* address){heap_caps_free(address);};
#else
 (void)zip;
#endif
}
}
