#pragma once

#include "ai.h"
#include "config.h"
#include "net.h"

#include <nlohmann/json.hpp>
#include <string>

namespace bili {

// Ported core of persona/psycho.py: action tracking, profile surface,
// aversion hints, info-cocoon metrics and curiosity query fallbacks.
nlohmann::json psycho_status(const App& app);
nlohmann::json psycho_record_action(App& app, const std::string& action_type,
                                    const std::string& bvid,
                                    const std::string& title,
                                    const std::string& category);
nlohmann::json curiosity_status(const App& app);
nlohmann::json curiosity_run(App& app, NetClient& net, AiClient& ai, bool force = false);
nlohmann::json evolution_reflect(App& app, NetClient& net, AiClient& ai, bool force = false);
nlohmann::json psycho_deep_analyze(App& app, NetClient& net, AiClient& ai);

}  // namespace bili
