#pragma once

#include "config.h"

#include <nlohmann/json.hpp>
#include <string>
#include <vector>

namespace bili {

// Ported from core/factory_reset.py. Groups are fixed so a malformed request
// can never expand into an arbitrary path.
nlohmann::json preview_reset_groups(const App& app, const nlohmann::json& selected_groups);
int erase_reset_groups(const App& app, const nlohmann::json& selected_groups);

}  // namespace bili
