#pragma once
#include "esp_random.h"

namespace CycleTelemetry {
// An observation epoch, not an authentication token. Created once per firmware
// process; uptime records from different epochs must never be subtracted.
inline const char* bootIdentity() {
    struct Identity {
        char text[33]{};
        Identity() {
            unsigned char bytes[16];
            esp_fill_random(bytes,sizeof(bytes));
            const char* hex="0123456789abcdef";
            for(unsigned i=0;i<16;++i){text[i*2]=hex[bytes[i]>>4];text[i*2+1]=hex[bytes[i]&15];}
        }
    };
    static const Identity identity;
    return identity.text;
}
}
