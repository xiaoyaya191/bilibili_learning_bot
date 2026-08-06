#pragma once

#include "config.h"
#include "net.h"

#include <string>

namespace bili {

// Refresh SESSDATA/bili_jct using refresh_token, ported from api/auth.py.
bool refresh_cookies(App& app, NetClient& net, std::string& error);

}  // namespace bili
