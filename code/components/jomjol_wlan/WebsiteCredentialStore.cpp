#include "WebsiteCredentialStore.h"
#include "../../../shared/WebsiteCredentialEsp.h"
namespace AIEdgeAuth {
Credential& deviceCredential() {
    static NvsBackend backend;
    static Credential credential(backend);
    return credential;
}
}
