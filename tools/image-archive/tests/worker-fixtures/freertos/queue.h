#pragma once
#include "FreeRTOS.h"
#include <cstddef>
void* xQueueCreate(int,size_t);void vQueueDelete(void*);
int xQueueSend(void*,void*,int);int xQueueReceive(void*,void*,int);
