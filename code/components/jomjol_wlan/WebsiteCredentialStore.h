#pragma once
#include "../../../shared/WebsiteHttp.h"
namespace AIEdgeAuth {
// Startup and the single HTTP server task own access. No concurrent mutation.
WebsiteHttp& deviceWebsiteHttp();
}
