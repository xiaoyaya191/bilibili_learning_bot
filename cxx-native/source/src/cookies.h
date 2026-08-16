#pragma once

#include "config.h"

#include <string>

namespace bili {

class NetClient;

// Ensure bilibili_cookies.json has a valid buvid3 (UUID+infoc), fixing it in
// place like the Python BiliClient does.
bool ensure_buvid3(App& app);

// Fetch buvid3/buvid4 from Bilibili SPI like Python bilibili-api does.
bool ensure_buvid4(App& app, NetClient& net);

std::string cookie_header(const App& app);
std::string cookie_value(const App& app, const std::string& key);

}  // namespace bili
