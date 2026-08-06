#pragma once

#include <string>

#include "config.h"

namespace bili {

// Exports a knowledge-base note (looked up by bvid) to the requested format.
// fmt: txt | md | html | docx | pdf | ppt | mm
// Returns the output path on success, empty string on failure.
std::string export_note(const App& app, const std::string& bvid, const std::string& fmt,
                        std::string& error);

}  // namespace bili
