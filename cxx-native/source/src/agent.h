#pragma once

#include "ai.h"
#include "config.h"
#include "net.h"

#include <nlohmann/json.hpp>
#include <string>

namespace bili {

// Runs a persistent learning-agent session with a bounded tool-calling loop.
// Returns the final assistant reply.
nlohmann::json run_learning_agent(App& app, NetClient& net, AiClient& ai,
                                  const std::string& type, const std::string& topic,
                                  const std::string& user_msg,
                                  const std::string& session_id, int max_steps = 6);

}  // namespace bili
