#pragma once

#include "net.h"

#include <nlohmann/json.hpp>
#include <string>

namespace bili {

// Multi-engine web search ported from knowledge/web_search.py:
// Bing -> Sogou -> DuckDuckGo -> Wikipedia.
nlohmann::json web_search(NetClient& net, const std::string& query, int limit);

}  // namespace bili
