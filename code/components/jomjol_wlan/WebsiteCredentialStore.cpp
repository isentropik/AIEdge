#include "WebsiteCredentialStore.h"
#include "../../../shared/WebsiteCredentialEsp.h"
namespace AIEdgeAuth {
WebsiteHttp& deviceWebsiteHttp() {
    static NvsBackend backend;
    static WebsiteAccess access(backend);
    static WebsiteHttp http(access);
    return http;
}
}
