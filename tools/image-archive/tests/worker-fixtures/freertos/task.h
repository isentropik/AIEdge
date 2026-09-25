#pragma once
int xTaskCreate(void(*)(void*),const char*,int,void*,int,void*);void vTaskDelay(int);
inline unsigned uxTaskGetStackHighWaterMark(void*){return 1024;}
