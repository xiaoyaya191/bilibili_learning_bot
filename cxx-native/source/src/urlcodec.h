#pragma once

#include <string>
#include <utility>
#include <vector>

namespace bili {

// application/x-www-form-urlencoded encoding matching Python's
// urllib.parse.urlencode: space -> '+', unreserved chars kept, others %XX.
std::string percent_encode(const std::string& value);

std::string build_query_string(
    const std::vector<std::pair<std::string, std::string>>& params);

std::string percent_decode(const std::string& value);

}  // namespace bili
