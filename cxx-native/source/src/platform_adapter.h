#pragma once

#include "config.h"
#include "net.h"

#include <nlohmann/json.hpp>
#include <string>

namespace bili {

// Minimal platform adapter: detects the platform and returns a download plan.
nlohmann::json platform_probe_url(const std::string& url);
nlohmann::json platform_download_plan(App& app, NetClient& net, const std::string& url);

}  // namespace bili
