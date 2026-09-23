#pragma once
#include "../../../shared/WebsiteAccess.h"
namespace AIEdgeAuth {
// Startup and the single HTTP server task own access. Callers must not race
// initialize/setup/check/change from background tasks.
WebsiteAccess& deviceWebsiteAccess();
}
