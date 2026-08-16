#pragma once

#include "config.h"

#include <string>

namespace bili {

// Runs the web QR login flow, saves bilibili_cookies.json on success.
bool run_login(App& app, const std::string& qr_path, int timeout_sec = 180);

}  // namespace bili
