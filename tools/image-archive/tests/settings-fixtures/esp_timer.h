#pragma once
#include <cstdint>
extern int64_t fake_time; inline int64_t esp_timer_get_time(){return fake_time;}
