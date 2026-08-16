#pragma once

#include "ai.h"
#include "config.h"
#include "net.h"

#include <nlohmann/json.hpp>
#include <string>

namespace bili {

// AI verification helpers for subtitles and web search results.
nlohmann::json verify_subtitle_ai(AiClient& ai, const std::string& title,
                                  const std::string& subtitle);
nlohmann::json verify_search_ai(AiClient& ai, const std::string& query,
                                const nlohmann::json& results);

}  // namespace bili
