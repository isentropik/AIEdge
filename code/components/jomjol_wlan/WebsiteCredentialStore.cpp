#include "WebsiteCredentialStore.h"
#include "../../../shared/WebsiteCredentialEsp.h"
namespace AIEdgeAuth {
WebsiteAccess& deviceWebsiteAccess() {
    static NvsBackend backend;
    static WebsiteAccess access(backend);
    return access;
}
}
