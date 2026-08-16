#pragma once

#include <nlohmann/json.hpp>
#include <string>

namespace bili {

// Ported from services/version_history.py: keeps a local copy of a note
// before it is regenerated and optionally writes a diff.
nlohmann::json save_note_version(const std::string& note_path, const std::string& content,
                                 const nlohmann::json& config);

}  // namespace bili
