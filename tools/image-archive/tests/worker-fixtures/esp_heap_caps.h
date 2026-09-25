#pragma once
#include <cstddef>
const int MALLOC_CAP_SPIRAM=1,MALLOC_CAP_8BIT=2,MALLOC_CAP_INTERNAL=4;
void* heap_caps_malloc(size_t,int);void heap_caps_free(void*);
inline size_t heap_caps_get_free_size(unsigned caps){return caps*100;}
inline size_t heap_caps_get_largest_free_block(unsigned caps){return caps*80;}
inline size_t heap_caps_get_minimum_free_size(unsigned caps){return caps*60;}
