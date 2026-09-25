#pragma once
using StackType_t=unsigned char;using portMUX_TYPE=int;using QueueHandle_t=void*;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(p) ((void)(p))
#define portEXIT_CRITICAL(p) ((void)(p))
#define pdMS_TO_TICKS(x) (x)
#define pdTRUE 1
#define pdPASS 1
