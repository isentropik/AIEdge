#pragma once
#include "../../../shared/WebsiteCredential.h"
namespace AIEdgeAuth {
// Startup and the single HTTP server task own access. Callers must not race
// load/save/verify from background tasks. Password writes need explicit auth.
Credential& deviceCredential();
}
