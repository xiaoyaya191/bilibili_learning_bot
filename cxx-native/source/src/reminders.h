#pragma once

#include "config.h"

#include <nlohmann/json.hpp>
#include <string>

namespace bili {

// Local reminder store, ported from services/reminders.py.
nlohmann::json parse_reminder_time_json(const std::string& text, long long now_ts = 0);
nlohmann::json create_reminder(const App& app, const std::string& text,
                               const std::string& owner_uid);
nlohmann::json take_due_reminders(const App& app);
nlohmann::json list_reminders(const App& app);

}  // namespace bili
