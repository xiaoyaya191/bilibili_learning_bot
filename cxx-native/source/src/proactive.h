#pragma once

#include "config.h"
#include "monitor.h"

#include <nlohmann/json.hpp>

namespace bili {

// Proactive browsing + self-evolution state machine, ported from
// xingye_bot/proactive.py and xingye_bot/evolution.py.
nlohmann::json run_proactive_cycle(App& app, Monitor& monitor);
nlohmann::json run_evolution_cycle(App& app);
nlohmann::json proactive_status(const App& app);
nlohmann::json evolution_status(const App& app);

}  // namespace bili
